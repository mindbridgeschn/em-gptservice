import os
import logging
from dotenv import load_dotenv
from openai import AzureOpenAI, AsyncAzureOpenAI

load_dotenv()
logger = logging.getLogger(__name__)

async_client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_API_KEY"),
    api_version="2024-12-01-preview",
    azure_endpoint=os.getenv("azure_endpoint"),
)

sync_client = AzureOpenAI(
    api_key=os.getenv("AZURE_API_KEY"),
    api_version="2024-12-01-preview",
    azure_endpoint=os.getenv("azure_endpoint"),
)

async def ai_call(text, prompt):
    logger.info("[AI] Async call started model=gpt-4o-mini prompt_len=%d text_len=%d", len(prompt), len(text))
    try:
        response = await async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content
        logger.info("[AI] Async call completed response_len=%d", len(content) if content else 0)
        return content
    except Exception as e:
        logger.error("[AI] Async call failed error=%s", e)
        raise


def ai_call_demo(text, prompt):
    logger.info("[AI] Sync call started model=gpt-4o-mini prompt_len=%d text_len=%d", len(prompt), len(text))
    try:
        response = sync_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content
        logger.info("[AI] Sync call completed response_len=%d", len(content) if content else 0)
        return content
    except Exception as e:
        logger.error("[AI] Sync call failed error=%s", e)
        raise
