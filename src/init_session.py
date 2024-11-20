from telethon.sync import TelegramClient
import json
import os

def init_session():
    # Load config
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Create sessions directory if it doesn't exist
    os.makedirs('sessions', exist_ok=True)

    # Initialize session for each account
    for phone in config['accounts']:
        print(f"Initializing session for {phone}")
        client = TelegramClient(f'sessions/{phone}', 
                              config['api_id'], 
                              config['api_hash'])
        
        try:
            client.connect()
            if not client.is_user_authorized():
                print(f"Sending code request to {phone}")
                client.send_code_request(phone)
                code = input(f"Enter the code received on {phone}: ")
                client.sign_in(phone, code)
                print(f"Successfully logged in with {phone}")
            else:
                print(f"Already authorized for {phone}")
        except Exception as e:
            print(f"Error with {phone}: {str(e)}")
        finally:
            client.disconnect()

    print("Session initialization completed!")

if __name__ == "__main__":
    init_session()
