import random
from pathlib import Path

class RandomUserAgent:
    _user_agents = None
    
    @classmethod
    def _load_user_agents(cls):
        if cls._user_agents is None:
            ua_file = Path(__file__).parent / "user_agents.txt"
            
            try:
                with open(ua_file, 'r', encoding='utf-8') as f:
                    cls._user_agents = [line.strip() for line in f if line.strip()]
                
                if not cls._user_agents:
                    raise ValueError("user_agents.txt is empty")
                    
            except FileNotFoundError:
                print(f"Warning: {ua_file} not found, using default user agent")
                cls._user_agents = [
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                ]
            except Exception as e:
                print(f"Error loading user agents: {e}")
                cls._user_agents = [
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                ]
    
    @classmethod
    def get(cls) -> str:
        if cls._user_agents is None:
            cls._load_user_agents()
        return random.choice(cls._user_agents)
