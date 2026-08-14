"""The Taskiq broker.

Its own module so task handlers and the API can both import it without
importing each other's handlers.
"""

from taskiq_redis import ListQueueBroker

from app.core.config import settings

broker = ListQueueBroker(settings.redis_url)
