import bisect
import datetime
import itertools
from typing import Generator, Iterable, Optional

import tweepy
from cachetools import LRUCache, TTLCache
from pydantic import BaseModel


class User(BaseModel):
    class Config:
        frozen = True

    id: int
    name: str
    username: str


class Media(BaseModel):
    class Config:
        frozen = True

    url: str


class Tweet(BaseModel):
    class Config:
        frozen = True

    id: int
    text: str
    created_at: datetime.datetime
    author: User
    medias: Optional[list[Media]] = None


class TTLTweetStore:
    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._tweets: list[Tweet] = []

    def delete_old_tweets(self):
        i = bisect.bisect(
            a=list(reversed([tweet.created_at for tweet in self._tweets])),
            x=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=self.ttl),
        )

        self._tweets = self._tweets[: len(self._tweets) - i]

    def add(self, tweets: Iterable[Tweet]):
        self.delete_old_tweets()

        self._tweets = sorted(
            itertools.chain(tweets, self._tweets),
            key=lambda tweet: tweet.created_at,
            reverse=True,
        )

    def __iter__(self):
        self.delete_old_tweets()
        return self._tweets.__iter__()

    def __getitem__(self, item):
        return self._tweets[item]

    def __len__(self) -> int:
        return len(self._tweets)


class TwitterClient:
    def __init__(
        self,
        tweepy_client: tweepy.Client,
        user_cache_maxsize: int,
        user_cache_ttl: int,
        tweet_store_cache_maxsize: int,
        tweet_store_ttl: int,
    ) -> None:
        self.tweepy_client = tweepy_client
        self.user_cache_maxsize = user_cache_maxsize
        self.user_cache_ttl = user_cache_ttl
        self.tweet_store_cache_maxsize = tweet_store_cache_maxsize
        self.tweet_store_ttl = tweet_store_ttl

        self.user_by_id_cache: TTLCache[int, User] = TTLCache(
            maxsize=self.user_cache_maxsize, ttl=self.user_cache_ttl
        )
        self.user_by_username_cache: TTLCache[str, User] = TTLCache(
            maxsize=self.user_cache_maxsize, ttl=self.user_cache_ttl
        )
        self.tweet_stores: LRUCache[int, TTLTweetStore] = LRUCache(
            maxsize=self.tweet_store_cache_maxsize
        )

    def get_user_by_id(self, id: int) -> User:
        try:
            return self.user_by_id_cache[id]
        except KeyError:
            user = User(**self.tweepy_client.get_user(id=id).data)

            self.user_by_id_cache[user.id] = user
            self.user_by_username_cache[user.username] = user

            return user

    def get_user_by_username(self, username: str) -> User:
        try:
            return self.user_by_username_cache[username]
        except KeyError:
            user = User(**self.tweepy_client.get_user(username=username).data)

            self.user_by_id_cache[user.id] = user
            self.user_by_username_cache[user.username] = user

            return user

    @staticmethod
    def _tweepy_get_users_tweets_response_to_tweets(
        response: tweepy.Response,
    ) -> Iterable[Tweet]:
        tweepy_tweets: list[tweepy.Tweet] = response.data
        included_users: dict[int, tweepy.User] = (
            {user.id: user for user in response.includes["users"]}
            if "users" in response.includes
            else dict()
        )
        included_medias: dict[str, tweepy.Media] = (
            {media.media_key: media for media in response.includes["media"]}
            if "media" in response.includes
            else dict()
        )

        return [
            Tweet(
                **tweepy_tweet,
                author=User(**included_users[tweepy_tweet.author_id]),
                medias=[
                    Media(**included_medias[media_key])
                    for media_key in tweepy_tweet.attachments["media_keys"]
                ]
                if tweepy_tweet.attachments and "media_keys" in tweepy_tweet.attachments
                else None,
            )
            for tweepy_tweet in tweepy_tweets
        ]

    def _fetch_newer_tweets(
        self, user_id: int, since_tweet_id: Optional[int] = None
    ) -> Iterable[Tweet]:
        """Fetch tweets from the user, which are newer than the tweet of the given id."""

        def tweets_generator() -> Generator[Iterable[Tweet], None, None]:
            pagination_token = None

            start_time = datetime.datetime.now(
                datetime.timezone.utc
            ) - datetime.timedelta(seconds=self.tweet_store_ttl)

            while True:
                response = self.tweepy_client.get_users_tweets(
                    id=user_id,
                    max_results=100,
                    since_id=since_tweet_id,
                    pagination_token=pagination_token,
                    start_time=start_time,
                    expansions=["author_id", "attachments.media_keys"],
                    media_fields=["url"],
                    tweet_fields=["created_at"],
                )

                if response.data is None:
                    break

                yield self._tweepy_get_users_tweets_response_to_tweets(response)

                if "next_token" not in response.meta:
                    break

                pagination_token = response.meta["next_token"]

        return itertools.chain.from_iterable(tweets_generator())

    def get_users_tweets(self, id: int) -> Iterable[Tweet]:
        if id not in self.tweet_stores:
            self.tweet_stores[id] = TTLTweetStore(ttl=self.tweet_store_ttl)

        try:
            since_tweet_id = self.tweet_stores[id][0].id
        except IndexError:
            since_tweet_id = None

        self.tweet_stores[id].add(
            self._fetch_newer_tweets(user_id=id, since_tweet_id=since_tweet_id)
        )

        return self.tweet_stores[id]
