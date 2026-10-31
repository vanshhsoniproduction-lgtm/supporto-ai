class PromptBuilder:
    """Builds grounded, context-limited prompts for Supporto AI with strict token budgeting."""

    @staticmethod
    def build_chat_prompt(
        system_prompt: str,
        company_name: str,
        retrieved_context: list[dict],
        message_history: list[dict],
        customer_message: str
    ) -> str:
        prompt_parts = [
            f"<|im_start|>system\n{system_prompt.strip()}\n",
            f"You are the official customer AI support assistant for {company_name}.",
            "CRITICAL RULES:",
            "1. Answer directly and concisely in 1 to 2 clear sentences. Never use chain-of-thought or reasoning steps.",
            "2. Base your answer strictly on the provided company knowledge and order details below.",
            "3. If the user's issue cannot be resolved or involves double charges or refund complaints, offer immediate escalation to staff.",
            "4. Do NOT output <think> tags. Output only the final friendly message for the customer.\n",
        ]

        if retrieved_context:
            prompt_parts.append("--- COMPANY KNOWLEDGE BASE CONTEXT ---")
            for idx, c in enumerate(retrieved_context[:3], 1):
                title = c.get('title', 'Policy')
                snippet = c.get('content', '')[:350].strip()
                prompt_parts.append(f"[{idx}] {title}:\n{snippet}\n")
            prompt_parts.append("--------------------------------------\n")
        else:
            prompt_parts.append("No specific documentation found for this question.\n")

        prompt_parts.append("<|im_end|>")

        for msg in (message_history or [])[-3:]:
            role = "user" if msg.get("sender_type") in ("CUSTOMER", "customer") else "assistant"
            content = (msg.get("content") or "").strip()[:200]
            if content:
                prompt_parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")

        # Standard clean ChatML prompt for Qwen
        prompt_parts.append(f"<|im_start|>user\n{customer_message.strip()}<|im_end|>\n<|im_start|>assistant\n")
        return "\n".join(prompt_parts)

prompt_builder = PromptBuilder()
