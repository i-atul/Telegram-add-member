#!/usr/bin/env python3

import sys
import os
import json
import logging
import asyncio
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.messages import GetHistoryRequest, SearchGlobalRequest
from telethon.tl.types import (
    ChannelParticipantsSearch, 
    ChannelParticipantsRecent,
    InputPeerChannel,
    User,
    Channel
)
from telethon.errors import ChatAdminRequiredError, FloodWaitError
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('scraping_members.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class MemberScraper:
    def __init__(self, config_path='config.json'):
        self.load_config(config_path)
        self.all_members = {}
        self.active_client = None
        
    def load_config(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def user_to_dict(self, user):
        """Convert a User object to a dictionary with all relevant information"""
        return {
            'id': user.id,
            'access_hash': user.access_hash,
            'username': user.username,
            'first_name': getattr(user, 'first_name', ''),
            'last_name': getattr(user, 'last_name', ''),
            'phone': getattr(user, 'phone', ''),
            'bot': user.bot if hasattr(user, 'bot') else False,
            'verified': user.verified if hasattr(user, 'verified') else False,
            'restricted': user.restricted if hasattr(user, 'restricted') else False,
            'scam': user.scam if hasattr(user, 'scam') else False,
            'fake': user.fake if hasattr(user, 'fake') else False,
            'premium': user.premium if hasattr(user, 'premium') else False
        }

    async def get_members_from_messages(self, client, group, limit=3000):
        """Get members who have sent messages"""
        try:
            logger.info("Getting members from recent messages...")
            async for message in client.iter_messages(group, limit=limit):
                if message.sender and isinstance(message.sender, User):
                    if not message.sender.bot and not message.sender.deleted:
                        self.all_members[message.sender.id] = self.user_to_dict(message.sender)
            
            logger.info(f"Found {len(self.all_members)} members from messages")
        except Exception as e:
            logger.error(f"Error getting members from messages: {e}")

    async def get_members_from_reactions(self, client, group, limit=100):
        """Get members from message reactions"""
        try:
            logger.info("Getting members from reactions...")
            messages = await client.get_messages(group, limit=limit)
            for message in messages:
                try:
                    reactions = await client.get_message_reactions(group, message.id)
                    for reaction in reactions:
                        if isinstance(reaction.peer, User) and not reaction.peer.bot:
                            self.all_members[reaction.peer.id] = self.user_to_dict(reaction.peer)
                except Exception as e:
                    continue
        except Exception as e:
            logger.error(f"Error getting members from reactions: {e}")

    async def get_members_by_search(self, client, group):
        """Get members by searching with different patterns"""
        search_patterns = [
            # Letters
            'a', 'e', 'i', 'o', 'u',
            # Common name starts
            'al', 'an', 'be', 'ch', 'de', 'el', 'jo', 'ka', 'ma', 'mi',
            'mo', 'ra', 'sa', 'sh', 'st', 'th', 'wi',
            # Numbers
            '1', '2', '3', '4', '5', '6', '7', '8', '9', '0'
        ]

        for pattern in search_patterns:
            try:
                logger.info(f"Searching with pattern: {pattern}")
                participants = await client(GetParticipantsRequest(
                    channel=group,
                    filter=ChannelParticipantsSearch(pattern),
                    offset=0,
                    limit=200,
                    hash=0
                ))
                
                for user in participants.users:
                    if isinstance(user, User) and not user.bot and not user.deleted:
                        self.all_members[user.id] = self.user_to_dict(user)
                
                logger.info(f"Found {len(participants.users)} members with pattern '{pattern}'")
                await asyncio.sleep(2)  # Avoid flood
                
            except FloodWaitError as e:
                logger.warning(f"Hit flood limit, waiting {e.seconds} seconds")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"Error searching with pattern '{pattern}': {e}")

    async def get_members_from_recent(self, client, group):
        """Get recent members"""
        try:
            logger.info("Getting recent members...")
            participants = await client(GetParticipantsRequest(
                channel=group,
                filter=ChannelParticipantsRecent(),
                offset=0,
                limit=200,
                hash=0
            ))
            
            for user in participants.users:
                if isinstance(user, User) and not user.bot and not user.deleted:
                    self.all_members[user.id] = self.user_to_dict(user)
                    
            logger.info(f"Found {len(participants.users)} recent members")
        except Exception as e:
            logger.error(f"Error getting recent members: {e}")

    async def run(self):
        # Create directories
        os.makedirs('sessions', exist_ok=True)
        os.makedirs('data', exist_ok=True)
        
        phone = self.config['accounts'][0]
        session_file = f'sessions/{phone}'
        
        logger.info(f"Using session file: {session_file}")
        
        client = TelegramClient(session_file,
                              self.config['api_id'], 
                              self.config['api_hash'])
        
        try:
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.error("Session not authorized. Please run init_session.py first")
                return
            
            # Get source group
            source_group = await client.get_entity(self.config['group_source'])
            logger.info(f"Successfully found group: {getattr(source_group, 'title', self.config['group_source'])}")
            
            # Use all methods to get members
            await self.get_members_from_recent(client, source_group)
            await self.get_members_from_messages(client, source_group)
            await self.get_members_from_reactions(client, source_group)
            await self.get_members_by_search(client, source_group)
            
            # Save results
            members_list = list(self.all_members.values())
            if members_list:
                output_file = os.path.join('data', f"members_{self.config['group_source']}.json")
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(members_list, f, indent=4, ensure_ascii=False)
                logger.info(f"Successfully saved {len(members_list)} unique members to {output_file}")
                
                # Save statistics
                stats = {
                    'total_members': len(members_list),
                    'with_username': len([m for m in members_list if m['username']]),
                    'with_phone': len([m for m in members_list if m['phone']]),
                    'premium_users': len([m for m in members_list if m['premium']]),
                    'verified_users': len([m for m in members_list if m['verified']]),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                with open('data/scraping_stats.json', 'w', encoding='utf-8') as f:
                    json.dump(stats, f, indent=4)
                logger.info("Saved scraping statistics")
                
            else:
                logger.error("No members found!")
                
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
        finally:
            await client.disconnect()

if __name__ == "__main__":
    # Set default encoding to UTF-8
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
        
    scraper = MemberScraper()
    asyncio.run(scraper.run())