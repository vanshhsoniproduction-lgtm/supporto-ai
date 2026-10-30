class PromptBuilder:
    """Builds grounded, context-limited prompts for Supporto AI."""

    @staticmethod
    def build_chat_prompt(system_prompt: str, company_name: str, retrieved_context: list[dict], message_history: list[dict], customer_message: str) -> str:
        prompt_parts = [
            f"<|im_start|>system\n{system_prompt}\n",
            f"You are responding on behalf of {company_name}.",
            "CRITICAL RULES:",
            "1. Base your answer strictly on the provided company knowledge below.",
            "2. If the user's issue cannot be resolved by the documentation or involves double-charge/billing/urgent problems, offer to escalate immediately.",
            "3. Do not invent order numbers, fake tracking codes, or personal account details.",
            "4. Keep your answer concise, friendly, and professional.\n",
        ]

        if retrieved_context:
            prompt_parts.append("--- COMPANY KNOWLEDGE BASE CONTEXT ---")
            for idx, c in enumerate(retrieved_context, 1):
                prompt_parts.append(f"[{idx}] {c['title']}:\n{c['content']}\n")
            prompt_parts.append("--------------------------------------\n")
        else:
            prompt_parts.append("No specific documentation found for this question.\n")

        prompt_parts.append("<|im_end|>")

        for msg in message_history[-6:]:
            role = "user" if msg["sender_type"] == "CUSTOMER" else "assistant"
            prompt_parts.append(f"<|im_start|>{role}\n{msg['content']}<|im_end|>")

        prompt_parts.append(f"<|im_start|>user\n{customer_message}<|im_end|>\n<|im_start|>assistant\n")
        return "\n".join(prompt_parts)

prompt_builder = PromptBuilder()

