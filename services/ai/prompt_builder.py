class PromptBuilder:
    """Builds grounded, context-limited prompts for Supporto AI with zero-latency thinking bypass."""

    @staticmethod
    def build_chat_prompt(system_prompt: str, company_name: str, retrieved_context: list[dict], message_history: list[dict], customer_message: str) -> str:
        prompt_parts = [
            f"<|im_start|>system\n{system_prompt}\n",
            f"You are the official customer AI support assistant for {company_name}.",
            "CRITICAL RULES:",
            "1. Answer directly and concisely in 1 to 2 clear sentences. Never use chain-of-thought or reasoning steps.",
            "2. Base your answer strictly on the provided company knowledge and order details below.",
            "3. If the user's issue cannot be resolved or involves double charges or refund complaints, offer immediate escalation to staff.",
            "4. Do NOT output <think> tags. Output only the final friendly message for the customer.\n",
        ]

        if retrieved_context:
            prompt_parts.append("--- COMPANY KNOWLEDGE BASE CONTEXT ---")
            for idx, c in enumerate(retrieved_context, 1):
                prompt_parts.append(f"[{idx}] {c['title']}:\n{c['content']}\n")
            prompt_parts.append("--------------------------------------\n")
        else:
            prompt_parts.append("No specific documentation found for this question.\n")

        prompt_parts.append("<|im_end|>")

        for msg in message_history[-4:]:
            role = "user" if msg["sender_type"] == "CUSTOMER" else "assistant"
            prompt_parts.append(f"<|im_start|>{role}\n{msg['content']}<|im_end|>")

        # Crucial: Pre-closing <think></think> instructs thinking LLMs (Qwen 2.5/3, DeepSeek) to skip internal reasoning
        prompt_parts.append(f"<|im_start|>user\n{customer_message}<|im_end|>\n<|im_start|>assistant\n<think>\n</think>\n")
        return "\n".join(prompt_parts)

prompt_builder = PromptBuilder()
