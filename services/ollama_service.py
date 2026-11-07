import os
from groq import Groq


def ask_ollama(prompt):
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL")

    if not api_key:
        return {
            "ok": False,
            "error": "GROQ_API_KEY is not configured."
        }

    if not model:
        return {
            "ok": False,
            "error": "GROQ_MODEL is not configured."
        }

    try:
        client = Groq(
            api_key=api_key,
            timeout=120.0
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a legal document analysis assistant. "
                        "Answer based on the supplied document context. "
                        "Do not invent facts, clauses, or legal citations. "
                        "Clearly mention uncertainty. "
                        "Your response is informational, not legal advice."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2
        )

        answer = (response.choices[0].message.content or "").strip()

        return {
            "ok": bool(answer),
            "text": answer,
            "error": "" if answer else "AI returned an empty response."
        }

    except Exception as e:
        return {
            "ok": False,
            "error": f"Hosted AI request failed: {str(e)}"
        }