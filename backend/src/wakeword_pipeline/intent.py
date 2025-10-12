# backend/src/speech_pipeline/intent.py

import os
import spacy
from typing import Dict, Any

class IntentInference:
    def __init__(self, model_dir: str):
        """
        model_dir: path to the saved spaCy model directory (the root folder containing textcat, vocab, etc.)
        """
        # Check if directory exists
        if not os.path.isdir(model_dir):
            raise FileNotFoundError(f"Intent model directory not found: {model_dir}")

        # Load the spaCy model
        self.nlp = spacy.load(model_dir)
        if "textcat" not in self.nlp.pipe_names:
            raise ValueError(f"Loaded spaCy pipeline does not contain 'textcat'. Available pipes: {self.nlp.pipe_names}")

    def predict_intent(self, text: str) -> Dict[str, Any]:
        """
        Given input text, returns a dict:
          {
            "intent": str,
            "confidence": float,
            "all_scores": { intent_label: float, … }
          }
        """
        doc = self.nlp(text)
        cats = doc.cats  # spaCy stores classification scores in doc.cats
        if not cats:
            # If empty (no classification), fallback
            return {
                "intent": "unknown",
                "confidence": 0.0,
                "all_scores": {}
            }
        # best intent = label with highest score
        best_label = max(cats, key=lambda lbl: cats[lbl])
        best_score = cats[best_label]
        return {
            "intent": best_label,
            "confidence": best_score,
            "all_scores": cats
        }

# For quick standalone testing when run directly
if __name__ == "__main__":
    # Derive model path relative to this file
    curr_dir = os.path.dirname(__file__)
    # e.g. go up to project root and into Config
    model_path = os.path.abspath(os.path.join(curr_dir, "../../Config/intent_classifier"))

    infer = IntentInference(model_path)

    test_texts = [
        "Add buy milk to my todo",
        "Hello, how are you?",
        "Give me a quote",
        "I want to write in my journal",
        "random garbage input"
    ]

    print("Intent Classification Results:")
    for t in test_texts:
        result = infer.predict_intent(t)
        print(f"Text: {repr(t)}")
        print(f" → Intent: {result['intent']} (confidence {result['confidence']:.3f})")
        print("   All scores:", result["all_scores"])
        print()
