from instagrapi import Client as InstagrapiClient
from hikerapi import Client as HikerClient
import time
from decouple import config
import os
from instagrowthwebapp.bot.comments import comments
import random
import logging
from datetime import datetime
import json

os.makedirs('data/logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(f'data/logs/growthbot_{datetime.now().strftime("%Y-%m-%d")}.log'),
        logging.StreamHandler()  # also prints to terminal
    ]
)

logger = logging.getLogger('GrowthBot')

DATA_FILE = 'data/data.json'
MAX_POSTS_PER_SESSION = config('MAX_POSTS_PER_SESSION', cast=int)
MAX_FOLLOW_PER_SESSION = config('MAX_FOLLOW_PER_SESSION', cast=int)
MAX_COMMENTS_PER_SESSION = config('MAX_COMMENTS_PER_SESSION', cast=int)

TARGETS = [
    {
        'username': config('TARGET_USER_1_USERNAME'),
        'user_id': config('TARGET_USER_1_USER_ID')
    },
    {
        'username': config('TARGET_USER_2_USERNAME'),
        'user_id': config('TARGET_USER_2_USER_ID')
    }
] 

class GrowthBot:

    def __init__(self, target_user_username=None):
        logger.info('Initializing GrowthBot...')
        self.insta_client = InstagrapiClient()
        
        proxy_url = f"http://{config('PROXY_LOGIN')}:{config('PROXY_PASSWORD')}@{config('PROXY_HOST')}:{config('PROXY_PORT')}"
        self.insta_client.set_proxy(proxy_url)
        logger.info('Proxy configured')

        self.insta_client.delay_range = [1, 3]

        session_file = "data/session.json"

        if os.path.exists(session_file):
            logger.info('Session file found. Loading session...')
            self.insta_client.load_settings(session_file)
            self.insta_client.login(config('INSTA_USERNAME'), config('INSTA_PASSWORD'))
            self.insta_client.dump_settings(session_file)
            logger.info(f'Logged in as {config("INSTA_USERNAME")}')
        else:
            logger.warning('No session file found. Prompting for session ID...')
            session_id = input("No session found. Paste your Instagram sessionid cookie: ").strip()
            self.insta_client.login_by_sessionid(session_id)
            self.insta_client.dump_settings(session_file)
            logger.info('Session saved successfully. Will reuse on next run.')

        self.hiker_client = HikerClient(token=config('HIKER_CLIENT_TOKEN'))
        logger.info('HikerAPI client initialized')

        if target_user_username is not None:
            if target_user_username == 'random':
                target_user = random.choice(TARGETS)
                self.target_user_id = target_user.get('user_id')
                logger.info(f"Random selection: @{target_user.get('username')}")
            else:
                logger.info(f'Fetching user ID for target: @{target_user_username}')
                self.target_user_id = self.__get_target_user_id(target_user_username)
                
            logger.info(f'Target user ID: {self.target_user_id}')

    def __get_target_user_id(self, username):
        result = self.hiker_client.user_by_username_v1(username=username)
        return result['pk']

    def __get_target_user_posts_ids(self):
        logger.info(f'Fetching posts for user ID: {self.target_user_id}')
        result = self.hiker_client.user_medias_chunk_v1(user_id=self.target_user_id)
        post_ids = [post.get('id') for post in result[0]]
        logger.info(f'Found {len(post_ids)} posts')
        return post_ids[:MAX_POSTS_PER_SESSION]

    def __extract_commenters_user_ids(self, comments):
        user_ids = [comment['user']['id'] for comment in comments]
        data = self.__load_data()
        data['user_ids'] = user_ids
        self.__save_data(data)
        logger.info(f'Extracted {len(user_ids)} commenter IDs and saved to data/data.json')
        return user_ids[:MAX_FOLLOW_PER_SESSION]

    def __get_posts_comments(self, post_ids):
        logger.info(f'Fetching comments from {len(post_ids)} posts...')
        comments = []
        for post_id in post_ids:
            result = self.hiker_client.media_comments_v2(id=post_id)
            batch = result.get('response').get('comments')
            comments.extend(batch)
            logger.info(f'  Post {post_id}: fetched {len(batch)} comments')
        logger.info(f'Total comments fetched: {len(comments)}')
        return comments


    def __load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        return {"user_ids": [], "last_followed_user_id": "", "last_unfollowed_user_id": ""}

    def __save_data(self, data):
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)

    def __follow_user(self, user_id):
        self.insta_client.user_follow(user_id=user_id)
        data = self.__load_data()
        data['last_followed_user_id'] = user_id
        self.__save_data(data)

    def unfollow_users(self):
        logger.info('=== Starting unfollow session ===')

        if not os.path.exists(DATA_FILE):
            logger.warning('data.json not found. Nothing to unfollow.')
            return

        data = self.__load_data()
        user_ids = data['user_ids']
        last_unfollowed = data['last_unfollowed_user_id']

        if not user_ids or len(user_ids) == 1:
            logger.info('Unfollow queue exhausted. Nothing left to unfollow.')
            data['last_unfollowed_user_id'] = ''
            self.__save_data(data)
            return

        # Resume from where we left off
        if last_unfollowed and last_unfollowed in user_ids:
            last_index = user_ids.index(last_unfollowed)
            user_ids = user_ids[last_index + 1 : last_index + 1 + MAX_FOLLOW_PER_SESSION]
            logger.info(f'Resuming unfollow from after user {last_unfollowed} (index {last_index})')
        else:
            user_ids = user_ids[:MAX_FOLLOW_PER_SESSION]
            logger.info('No previous unfollow position found. Starting from beginning of queue.')

        logger.info(f'Preparing to unfollow {len(user_ids)} users...')
        success, failed = 0, 0

        for user_id in user_ids:
            try:
                self.insta_client.user_unfollow(user_id)
                logger.info(f'  Unfollowed user: {user_id}')
                data['last_unfollowed_user_id'] = user_id
                self.__save_data(data)
                success += 1
            except Exception as e:
                logger.error(f'  Failed to unfollow {user_id}: {e}')
                failed += 1
            time.sleep(1)

        logger.info(f'=== Unfollow session complete | Unfollowed: {success} | Failed: {failed} ===')

    def __comment_on_posts(self, post_ids):
        logger.info(f'Commenting on {len(post_ids)} posts...')
        for post_id in post_ids:
            chosen = random.choice(comments)
            self.insta_client.media_comment(media_id=post_id, text=chosen)
            logger.info(f'  Commented on post {post_id}: "{chosen}"')

    def follow_commenters_from_target_user_posts(self):
        logger.info('=== Starting follow session ===')
        posts = self.__get_target_user_posts_ids()

        self.__comment_on_posts(posts[:MAX_COMMENTS_PER_SESSION])

        post_comments = self.__get_posts_comments(posts)

        data = self.__load_data()
        user_ids = data['user_ids']
        last_followed = data['last_followed_user_id']

        # If list is exhausted or empty, refresh from comments
        if not user_ids or len(user_ids) == 1:
            logger.info('User ID queue exhausted. Refreshing from comments...')
            data['user_ids'] = []
            data['last_followed_user_id'] = ''
            self.__save_data(data)
            user_ids = self.__extract_commenters_user_ids(post_comments)
        else:
            # Resume from where we left off
            if last_followed and last_followed in user_ids:
                last_index = user_ids.index(last_followed)
                user_ids = user_ids[last_index + 1 : last_index + 1 + MAX_FOLLOW_PER_SESSION]
                logger.info(f'Resuming from after user {last_followed} (index {last_index})')
            else:
                # No last_followed recorded, start from beginning
                user_ids = user_ids[:MAX_FOLLOW_PER_SESSION]
                logger.info('No previous position found. Starting from beginning of queue.')

        logger.info(f'Preparing to follow {len(user_ids)} users...')
        success, failed = 0, 0

        for user_id in user_ids:
            try:
                self.__follow_user(user_id=user_id)
                logger.info(f'  Followed user: {user_id}')
                success += 1
            except Exception as e:
                logger.error(f'  Failed to follow {user_id}: {e}')
                failed += 1
            time.sleep(1)

        logger.info(f'=== Follow session complete | Followed: {success} | Failed: {failed} ===')


bot = GrowthBot(target_user_username='random')
bot.follow_commenters_from_target_user_posts()
# bot.unfollow_users()