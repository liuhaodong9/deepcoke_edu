"""
DeepSeek language model adapter for ESCARGOT's AbstractLanguageModel.
Allows ESCARGOT reasoning to use DeepSeek API instead of Azure GPT.
"""
import sys
import time
import random
import logging
from typing import List, Dict, Union, Any
from pathlib import Path

from openai import OpenAI, OpenAIError
from openai.types.chat.chat_completion import ChatCompletion

# Add escargot to path
sys.path.insert(0, str(Path(r"D:\escargot")))

from escargot.language_models.abstract_language_model import AbstractLanguageModel
from .. import config


class DeepSeekLM(AbstractLanguageModel):
    """
    DeepSeek language model adapter for ESCARGOT.
    Implements the AbstractLanguageModel interface using DeepSeek's
    OpenAI-compatible API.
    """

    def __init__(self, logger: logging.Logger = None):
        # Initialize without calling super().__init__ to avoid config file loading
        self.logger = logger or logging.getLogger(__name__)
        self.config = {}
        self.model_name = "deepseek"
        self.cache = False

        self.model_id = config.DEEPSEEK_MODEL
        self.temperature = 0.3
        self.max_tokens = 4096
        self.stop = None

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost = 0.0

        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )

    def query(
        self, query: str, num_responses: int = 1
    ) -> Union[List[ChatCompletion], ChatCompletion]:
        """Query DeepSeek for responses."""
        if num_responses == 1:
            return self.chat([{"role": "user", "content": query}], num_responses)

        # For multiple responses, call one at a time (DeepSeek may not support n>1)
        responses = []
        for _ in range(num_responses):
            try:
                res = self.chat([{"role": "user", "content": query}], 1)
                responses.append(res)
            except Exception as e:
                self.logger.warning(f"DeepSeek query error: {e}")
                time.sleep(random.uniform(0.5, 2.0))
        return responses

    def chat(self, messages: List[Dict], num_responses: int = 1) -> ChatCompletion:
        """Send chat messages to DeepSeek."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    n=min(num_responses, 1),  # DeepSeek typically supports n=1
                )

                if response.usage:
                    self.prompt_tokens += response.usage.prompt_tokens
                    self.completion_tokens += response.usage.completion_tokens

                return response
            except OpenAIError as e:
                self.logger.warning(f"DeepSeek API error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def get_response_texts(
        self, query_response: Union[List[ChatCompletion], ChatCompletion]
    ) -> List[str]:
        """Extract response texts from the query response."""
        if not isinstance(query_response, list):
            query_response = [query_response]
        return [
            choice.message.content
            for response in query_response
            for choice in response.choices
            if choice.message.content
        ]
