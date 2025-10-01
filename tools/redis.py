
from config.setting import settings
import redis
import json
from redis.exceptions import ConnectionError as RedisConnectionError
from typing import List, Tuple


class RedisStateManager:
    """Handles saving and loading of conversational context (last_context and last_query)
    using Redis, keyed by a unique session ID."""

    def __init__(self, ):
        try:
            self.redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True
            )
            self.ttl = settings.CONTEXT_TTL_SECONDS
            self.redis_client.ping()
            
        except RedisConnectionError as e:
            print(f"Error connecting to Redis: {e}")
            print("Please ensure Redis is running or update REDIS_HOST/REDIS_PORT.")
            # Set to None to fail gracefully if Redis is unavailable
            self.redis_client = None

    def _get_key(self, session_id):
        """Standardized key format for multi-tenant environments."""
        return f"artifacts/{settings.APP_ID}/session/{session_id}/state"

    def load_state(self, session_id: str) -> Tuple[str, List[str]]:
        """Retrieves and deserializes the state for a given session ID."""
        if not self.redis_client:
            return "", []  # Fail gracefully to empty state

        key = self._get_key(session_id)
        try:
            serialized_state = self.redis_client.get(key)
            if serialized_state:
                state = json.loads(serialized_state)
                print(f"Loaded state for session: {session_id}")
                return state.get('last_query', ""), state.get('last_context', [])
            return "", []
        except Exception as e:
            print(f"Error loading state from Redis: {e}")
            return "", []

    def save_state(self, session_id: str, last_query: str, last_context: List[str]):
        """Serializes the state and saves it to Redis with an expiration."""
        if not self.redis_client:
            print("Cannot save state: Redis client not initialized.")
            return False

        key = self._get_key(session_id)
        try:
            state_data = {
                "last_query": last_query,
                "last_context": last_context
            }
            serialized_state = json.dumps(state_data)
            self.redis_client.set(key, serialized_state, ex=self.ttl)
            print(f"Saved state for session: {session_id}. TTL: {self.ttl}s")
            return True
        except Exception as e:
            print(f"Error saving state to Redis: {e}")
            return False
