#!/usr/bin/env python3

import sys
import os
import json
import logging
import asyncio
import random
from datetime import datetime, timedelta
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPeerUser, InputPeerChannel, User
from telethon.errors import (
    FloodWaitError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
    UserBannedInChannelError,
    UserBlockedError,
    UserIdInvalidError,
    PeerFloodError,
    ChatWriteForbiddenError
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('adding_members.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class MemberAdder:
    def __init__(self, config_path='config.json'):
        self.load_config(config_path)
        self.added_today = 0
        self.current_account_index = 0
        self.daily_stats = {phone: 0 for phone in self.config['accounts']}
        self.start_time = datetime.now()
        
    def load_config(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def load_members(self):
        """Load members from the scraped data file"""
        try:
            members_file = os.path.join('data', f"members_{self.config['group_source']}.json")
            with open(members_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading members: {e}")
            return []

    def save_progress(self, added_members):
        """Save the progress of added members"""
        try:
            progress_file = os.path.join('data', 'adding_progress.json')
            progress = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'added_members': added_members,
                'daily_stats': self.daily_stats
            }
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving progress: {e}")

    async def switch_account(self):
        """Switch to the next account in rotation"""
        self.current_account_index = (self.current_account_index + 1) % len(self.config['accounts'])
        logger.info(f"Switching to account: {self.config['accounts'][self.current_account_index]}")
        return self.config['accounts'][self.current_account_index]

    async def add_member(self, client, target_group, user_data):
        """Add a single member to the target group"""
        try:
            user_to_add = InputPeerUser(
                user_id=user_data['id'],
                access_hash=user_data['access_hash']
            )
            
            await client(InviteToChannelRequest(
                target_group,
                [user_to_add]
            ))
            
            delay = random.randint(self.config['min_delay'], self.config['max_delay'])
            logger.info(f"Successfully added user {user_data.get('username', user_data['id'])}. "
                       f"Waiting {delay} seconds...")
            await asyncio.sleep(delay)
            return True

        except FloodWaitError as e:
            logger.warning(f"Hit flood limit, waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
        except UserPrivacyRestrictedError:
            logger.warning(f"User {user_data.get('username', user_data['id'])} has privacy restrictions")
        except UserNotMutualContactError:
            logger.warning(f"User {user_data.get('username', user_data['id'])} is not a mutual contact")
        except UserBannedInChannelError:
            logger.warning(f"User {user_data.get('username', user_data['id'])} is banned in the channel")
        except UserBlockedError:
            logger.warning(f"User {user_data.get('username', user_data['id'])} has blocked the bot")
        except PeerFloodError:
            logger.warning("Too many requests, switching account")
            await self.switch_account()
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Unexpected error adding user {user_data.get('username', user_data['id'])}: {e}")
        
        return False

    async def run(self):
        """Main execution function"""
        # Create necessary directories
        os.makedirs('sessions', exist_ok=True)
        os.makedirs('data', exist_ok=True)

        # Load members
        members = self.load_members()
        if not members:
            logger.error("No members found to add!")
            return

        added_members = []
        current_phone = self.config['accounts'][self.current_account_index]
        session_file = f'sessions/{current_phone}'

        logger.info(f"Starting member addition process with {len(members)} members")
        
        while len(added_members) < self.config['members_to_add'] and members:
            client = TelegramClient(session_file,
                                  self.config['api_id'],
                                  self.config['api_hash'])
            
            try:
                await client.connect()
                
                if not await client.is_user_authorized():
                    logger.error(f"Session not authorized for {current_phone}. Please run init_session.py first")
                    await self.switch_account()
                    current_phone = self.config['accounts'][self.current_account_index]
                    session_file = f'sessions/{current_phone}'
                    continue

                # Get target group entity
                target_group = await client.get_entity(self.config['group_target'])
                
                # Check daily limit for current account
                if self.daily_stats[current_phone] >= self.config['max_adds_per_day_per_account']:
                    logger.warning(f"Daily limit reached for {current_phone}")
                    await self.switch_account()
                    current_phone = self.config['accounts'][self.current_account_index]
                    session_file = f'sessions/{current_phone}'
                    continue

                # Add members
                while members and len(added_members) < self.config['members_to_add']:
                    user_data = members.pop(0)
                    
                    if await self.add_member(client, target_group, user_data):
                        added_members.append(user_data)
                        self.daily_stats[current_phone] += 1
                        self.save_progress(added_members)

                    # Check if we need to switch account
                    if self.daily_stats[current_phone] >= self.config['max_adds_per_day_per_account']:
                        break

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(60)
                
            finally:
                await client.disconnect()

        # Save final progress
        self.save_progress(added_members)
        logger.info(f"Addition process completed. Added {len(added_members)} members")

if __name__ == "__main__":
    # Set default encoding to UTF-8
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
        
    adder = MemberAdder()
    asyncio.run(adder.run())
