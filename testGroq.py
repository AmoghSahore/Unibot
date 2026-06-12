import os

from dotenv import load_dotenv
from groq import Groq


load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

response = client.chat.completions.create(
    model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
    messages=[{"role": "user", "content": "Say hello in one sentence."}],
    temperature=0,
)

print(response.choices[0].message.content)
