import tweepy
from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from feedgen.feed import FeedGenerator
from pydantic import BaseSettings

from twitter_rss.twitter_client import TwitterClient


class Settings(BaseSettings):
    twitter_bearer_token: str
    user_cache_maxsize: int
    user_cache_ttl: int
    tweet_store_cache_maxsize: int
    tweet_store_ttl: int

    class Config:
        env_file = ".env"


settings = Settings()


client = TwitterClient(
    tweepy_client=tweepy.Client(bearer_token=settings.twitter_bearer_token),
    user_cache_maxsize=settings.user_cache_maxsize,
    user_cache_ttl=settings.user_cache_ttl,
    tweet_store_cache_maxsize=settings.tweet_store_cache_maxsize,
    tweet_store_ttl=settings.tweet_store_ttl,
)

app = FastAPI()


@app.get("/user/{username}")
def read_users_tweets(username: str):
    user = client.get_user_by_username(username=username)

    return RedirectResponse(f"/userid/{user.id}")


@app.get("/userid/{id}")
def read_users_tweets_by_id(id: int):
    user = client.get_user_by_id(id=id)

    fg = FeedGenerator()
    fg.title(f"{user.name} / @{user.username}")
    fg.link(href=f"https://twitter.com/{user.username}", rel="alternate")
    fg.description(f"Twitter feed for: {user.name} / @{user.username}.")

    tweets = client.get_users_tweets(id=user.id)

    for tweet in reversed(list(tweets)):
        fe = fg.add_entry()
        fe.title(tweet.text)
        fe.link(
            href=f"https://twitter.com/{tweet.author.username}/status/{tweet.id}",
            rel="alternate",
        )
        fe.description(
            f"<p>{tweet.text}</p>"
            + "".join(
                [f'<img src="{media.url}" />' for media in tweet.medias]
                if tweet.medias
                else []
            )
        )
        fe.author(
            name=f"{tweet.author.name} / @{tweet.author.username}",
            uri=f"https://twitter.com/{tweet.author.username}",
        )
        fe.guid(str(tweet.id))
        fe.pubDate(tweet.created_at)

    return Response(content=fg.rss_str(pretty=True), media_type="application/xml")
