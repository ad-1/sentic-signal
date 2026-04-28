"""RabbitMQ publisher for sending news items to a queue.

This module provides a simple interface for publishing NewsItem objects
to a RabbitMQ queue. It can be used by the ingestor modules to push
fetched news items to a message queue for further processing.
"""

import json
import logging
from typing import List

import pika
from pika.adapters.blocking_connection import BlockingChannel

from sentic_signal.models import NewsItem

logger = logging.getLogger(__name__)


class RabbitMQPublisher:
    """A simple RabbitMQ publisher for NewsItem objects."""

    def __init__(self, host: str = "localhost", port: int = 5672, queue_name: str = "news_queue"):
        """Initialize the RabbitMQ publisher.
        
        Args:
            host: RabbitMQ server host
            port: RabbitMQ server port
            queue_name: Name of the queue to publish to
        """
        self.host = host
        self.port = port
        self.queue_name = queue_name
        self.connection = None
        self.channel = None

    def connect(self):
        """Establish connection to RabbitMQ server."""
        try:
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            
            # Declare the queue (creates it if it doesn't exist)
            self.channel.queue_declare(queue=self.queue_name, durable=True)
            
            logger.info("Successfully connected to RabbitMQ at %s:%d", self.host, self.port)
            
        except Exception as e:
            logger.error("Failed to connect to RabbitMQ: %s", str(e))
            raise

    def publish_news_item(self, news_item: NewsItem) -> bool:
        """Publish a single NewsItem to the queue.
        
        Args:
            news_item: The NewsItem to publish
            
        Returns:
            True if successful, False otherwise
        """
        if not self.channel:
            logger.error("Not connected to RabbitMQ")
            return False
            
        try:
            # Convert NewsItem to dictionary for JSON serialization
            message = news_item.model_dump()
            
            # Publish the message
            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Make message persistent
                )
            )
            
            logger.info("Published news item to queue '%s': %s", self.queue_name, news_item.headline)
            return True
            
        except Exception as e:
            logger.error("Failed to publish news item: %s", str(e))
            return False

    def publish_news_items(self, news_items: List[NewsItem]) -> int:
        """Publish multiple NewsItem objects to the queue.
        
        Args:
            news_items: List of NewsItem objects to publish
            
        Returns:
            Number of items successfully published
        """
        if not self.channel:
            logger.error("Not connected to RabbitMQ")
            return 0
            
        success_count = 0
        for item in news_items:
            if self.publish_news_item(item):
                success_count += 1
                
        return success_count

    def close(self):
        """Close the connection to RabbitMQ."""
        if self.connection and not self.connection.is_closed:
            self.connection.close()
            logger.info("Closed connection to RabbitMQ")


def create_publisher_from_env() -> RabbitMQPublisher:
    """Create a RabbitMQ publisher using environment variables.
    
    Environment variables:
        RABBITMQ_HOST: RabbitMQ server host (default: localhost)
        RABBITMQ_PORT: RabbitMQ server port (default: 5672)
        RABBITMQ_QUEUE: Queue name (default: news_queue)
        
    Returns:
        RabbitMQPublisher instance
    """
    import os
    
    host = os.getenv("RABBITMQ_HOST", "localhost")
    port = int(os.getenv("RABBITMQ_PORT", "5672"))
    queue_name = os.getenv("RABBITMQ_QUEUE", "news_queue")
    
    return RabbitMQPublisher(host=host, port=port, queue_name=queue_name)


# Example usage
if __name__ == "__main__":
    # This is for testing purposes only
    logging.basicConfig(level=logging.INFO)
    
    # Create a test publisher
    publisher = create_publisher_from_env()
    
    try:
        publisher.connect()
        logger.info("RabbitMQ publisher ready for use")
    except Exception as e:
        logger.error("Could not initialize publisher: %s", str(e))
    finally:
        publisher.close()