import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("uuid"),
    api_version="2024-12-01-preview",
    azure_endpoint=os.getenv("azure_endpoint"),
)

async def ai_call(text, prompt):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text}
        ],
        temperature=0.0,
    )
    return response.choices[0].message.content


def ai_call_demo(text, prompt):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text}
        ],
        temperature=0.0,
    )
    return response.choices[0].message.content
