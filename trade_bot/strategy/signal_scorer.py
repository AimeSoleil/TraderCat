class SignalScorer:
    def __init__(self, threshold_percent=0.6):
        """
        Initializes the scorer with a percentage threshold.

        Args:
            threshold_percent (float): Minimum percentage of conditions that must be met to trigger a signal.
                                    Value should be between 0.0 and 1.0 (e.g., 0.6 means 60%).
        """
        self.conditions = []         # Conditions that passed
        self.total_possible = 0.0    # Total weight of all evaluated conditions
        self.threshold_percent = threshold_percent

    def add(self, condition: bool, reason: str, weight: float = 1.0):
        """
        Adds a condition to the scoring system.

        Args:
            condition (bool): Whether the condition is met.
            reason (str): Description of the condition.
            weight (float): Importance of the condition (default: 1.0).
        """
        self.total_possible += weight
        if condition:
            self.conditions.append((reason, weight))

    def evaluate(self, direction="bullish"):
        """
        Evaluates the signal based on accumulated conditions.

        Args:
            direction (str): 'bullish' or 'bearish' to determine signal polarity.

        Returns:
            signal (str): 'buy', 'sell', or 'hold'
            confidence (float): Normalized score between 0 and 1
            reasons (list): List of reasons for the signal
        """
        total_score = sum(weight for _, weight in self.conditions)
        max_score = self.total_possible or 1.0  # Avoid divide-by-zero
        confidence = round(total_score / max_score, 2)

        signal = "buy" if confidence >= self.threshold_percent else "hold"
        if direction == "bearish" and signal == "buy":
            signal = "sell"

        reasons = [reason for reason, _ in self.conditions]
        return signal, confidence, reasons
