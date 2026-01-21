from typing import List
from tradercat.ai.prompts import buffett, buffett_zh, livermore, livermore_zh, ptj, ptj_zh, wyckoff, wyckoff_zh

class PromptManager:
    """
    Manages AI persona templates via in-memory constants.
    """

    def __init__(self):
        self.PROMPT_REGISTRY = {        
            "wyckoff": wyckoff.PROMPT,
            "wyckoff-zh": wyckoff_zh.PROMPT,
            "livermore": livermore.PROMPT,
            "livermore-zh": livermore_zh.PROMPT,
            "buffett": buffett.PROMPT,
            "buffett-zh": buffett_zh.PROMPT,
            "ptj": ptj.PROMPT,
            "ptj-zh": ptj_zh.PROMPT,        
        }

        # IMPROVED PROMPT
        self.user_prompt_template = """
        **TASK:** Analyze the provided [MARKET DATA] strictly using the Persona defined in the System Prompt. 
        and output in the {lang_hit} language.

        **INPUT DATA:**
        ===BEGIN MARKET DATA===
        {data_json}
        ===END MARKET DATA===
        """
        # self.user_prompt_template = """
        # **TASK:** Analyze the provided [MARKET DATA] strictly using the Persona defined in the System Prompt.

        # **INPUT DATA:**
        # ===BEGIN MARKET DATA===
        # {data_json}
        # ===END MARKET DATA===

        # **INSTRUCTIONS:**
        # 1. **Data Integrity:** Do NOT repeat the raw JSON. Trust the data provided.
        # 2. **Technical Synthesis:** focus on the relationship between Price, Volume, and Volatility found in the data.
        # 3. **Pattern Recognition:** Identify specific setups (e.g., divergence, compression, breakout) visible in the numbers.

        # **REQUIRED OUTPUT FORMAT:**
        # Please output your response in the following Markdown structure:

        # ### 1. Market Context (Observation)
        # *   **Trend:** [Bullish / Bearish / Neutral] (Cite specific metrics like MA slope or High/Lows)
        # *   **Key Levels:** Support at $X, Resistance at $Y.
        # *   **Volume Profile:** [e.g., Expanding on bullish moves, drying up on pullbacks]

        # ### 2. Alpha Signal (Analysis)
        # *   **Pattern:** [Name the pattern or structure, e.g., Bull Flag, Double Bottom]
        # *   **Signal Strength:** [Low / Medium / High]
        # *   **Reasoning:** Concise explanation linking data points to the persona's logic.

        # ### 3. Execution Plan (The Trade)
        # *   **Direction:** [LONG / SHORT / WAIT]
        # *   **Entry Zone:** [Specific price range]
        # *   **Invalidation (Stop Loss):** [Price level where the thesis fails]
        # *   **Target (Take Profit):** [Price level based on RR]

        # ### 4. Risk Note
        # *   One sentence on the primary risk factor (e.g., Earnings ahead, low liquidity).
        # """

    def list_analysts(self) -> List[str]:
        """
        Returns a sorted list of unique available analyst keys (aliases).
        """
        return sorted(list(self.PROMPT_REGISTRY.keys()))

    def get_system_prompt(self, alias: str) -> str:
        """
        Retrieves the prompt content directly from memory.
        """
        alias_lower = alias.lower()
        
        if alias_lower not in self.PROMPT_REGISTRY:
            valid_keys = ", ".join(self.list_analysts()[:5]) + "..."
            raise ValueError(f"Unknown analyst alias: '{alias}'. Available: {valid_keys}")

        # Direct memory access - extremely fast & reliable
        return self.PROMPT_REGISTRY[alias_lower]

    def get_user_prompt(self, data_json: str | None, lang_hint: str = "en") -> str:
        """
        Retrieves the user prompt content directly from memory.
        """
        if lang_hint.lower() == 'zh':
            lang_hint = "Chinese"
        elif lang_hint.lower() == 'en':
            lang_hint = "English"
        else:
            lang_hint = "English"
        if data_json:
            return self.user_prompt_template.format(lang_hit=lang_hint, data_json=data_json)
        else:
            return self.user_prompt_template.format(lang_hit=lang_hint)