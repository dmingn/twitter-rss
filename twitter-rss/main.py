import tweepy
from fastapi import FastAPI, Response
from feedgen.feed import FeedGenerator
from pydantic import BaseSettings


class Settings(BaseSettings):
    twitter_bearer_token: str

    class Config:
        env_file = ".env"


settings = Settings()


client = tweepy.Client(bearer_token=settings.twitter_bearer_token)


app = FastAPI()


@app.get("/user/{username}")
def read_user(username: str):
    user: tweepy.User = client.get_user(username=username).data

    fg = FeedGenerator()
    fg.title(f"{user.name} / @{user.username}")
    fg.link(href=f"https://twitter.com/{user.username}", rel="alternate")
    fg.description(f"Twitter feed for: @{user.username}.")

    response = client.get_users_tweets(
        id=user.id,
        expansions=["author_id", "attachments.media_keys"],
        media_fields=["url"],
        tweet_fields=["created_at"],
    )

    tweets: list[tweepy.Tweet] = response.data
    included_user: dict[int, tweepy.User] = (
        {user.id: user for user in response.includes["users"]}
        if "users" in response.includes
        else dict()
    )
    included_media: dict[str, tweepy.Media] = (
        {media.media_key: media for media in response.includes["media"]}
        if "media" in response.includes
        else dict()
    )

    for tweet in reversed(tweets):
        author = included_user[tweet.author_id]
        media_urls = (
            [
                included_media[media_key].url
                for media_key in tweet.attachments["media_keys"]
            ]
            if tweet.attachments and "media_keys" in tweet.attachments
            else []
        )

        fe = fg.add_entry()
        fe.title(tweet.text)
        fe.link(
            href=f"https://twitter.com/{author.username}/status/{tweet.id}",
            rel="alternate",
        )
        fe.description(
            f"<![CDATA[<p>{tweet.text}</p>"
            + "".join([f'<img src="{media_url}" />' for media_url in media_urls])
            + "]]>"
        )
        fe.author(
            name=f"{author.name} / @{author.username}",
            uri=f"https://twitter.com/{author.username}",
        )
        fe.guid(str(tweet.id))
        fe.pubDate(tweet.created_at)

    return Response(content=fg.rss_str(pretty=True), media_type="application/xml")
