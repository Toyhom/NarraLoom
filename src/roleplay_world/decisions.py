"""Typed System One contracts; probabilities are evidence, never world authority."""

import json
import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Contract, Identifier


class DecisionQuestion(Contract):
    type: Literal["choice", "noul", "score"]
    instructions: Annotated[str, Field(min_length=1, max_length=4000)]
    criteria: dict[Identifier, str] | list[str] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.type == "noul":
            if self.criteria is not None:
                raise ValueError("noul does not take criteria")
        else:
            expected = dict if self.type == "choice" else list
            if not isinstance(self.criteria, expected) or not 2 <= len(self.criteria) <= 32:
                raise ValueError("choice takes 2–32 named options; score takes 2–32 ordered labels")
            values = self.criteria.values() if isinstance(self.criteria, dict) else self.criteria
            if any(not v.strip() or len(v) > 2000 for v in values):
                raise ValueError("criteria descriptions must contain 1–2000 characters")
        return self


class DecisionRequest(Contract):
    state: str | dict | list
    questions: Annotated[dict[Identifier, DecisionQuestion], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def bounded(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False)) > 120000:
            raise ValueError("decision request exceeds 120000 characters")
        return self


def probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability")
    return float(value)


def validate_response(request: DecisionRequest, raw: dict):
    """Strict semantic validation without silently renormalizing an invalid answer."""
    if not isinstance(raw, dict) or not isinstance(raw.get("model"), str) or not raw["model"]:
        raise ValueError("missing response model")
    answers = raw.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(request.questions):
        raise ValueError("response question set differs from request")
    validated = {}
    for name, question in request.questions.items():
        answer = answers[name]
        if not isinstance(answer, dict) or answer.get("type") != question.type:
            raise ValueError("response type differs from request")
        if question.type == "noul":
            yes = probability(answer.get("noul"))
            validated[name] = {"type": "noul", "noul": yes,
                               "probabilities": {"yes": yes, "no": 1 - yes},
                               "p_max": max(yes, 1 - yes), "margin": abs(2 * yes - 1)}
            continue
        keys = set(question.criteria) if question.type == "choice" else {str(i) for i in range(len(question.criteria))}
        distribution = answer.get("probabilities")
        if not isinstance(distribution, dict) or set(distribution) != keys:
            raise ValueError("response option set differs from request")
        probs = {key: probability(value) for key, value in distribution.items()}
        if not math.isclose(sum(probs.values()), 1, abs_tol=0.001):
            raise ValueError("probabilities do not sum to one")
        ranked = sorted(probs.values(), reverse=True)
        result = {"type": question.type, "probabilities": probs, "p_max": ranked[0],
                  "margin": ranked[0] - ranked[1]}
        if "confidence" in answer:
            result["confidence"] = probability(answer["confidence"])
        if question.type == "choice":
            selected = answer.get("choice")
            if not isinstance(selected, str) or selected not in probs or probs[selected] != ranked[0]:
                raise ValueError("choice must be a highest probability option")
            result["choice"] = selected
        else:
            expected = sum(int(key) * p for key, p in probs.items())
            score = answer.get("score")
            if (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)
                    or not 0 <= score <= len(keys) - 1 or not math.isclose(score, expected, abs_tol=0.01)):
                raise ValueError("score differs from distribution expectation")
            legend = {str(i): text for i, text in enumerate(question.criteria)}
            if answer.get("legend", legend) != legend:
                raise ValueError("score legend differs from request")
            result.update(score=score, legend=legend)
        validated[name] = result
    usage = raw.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            raise ValueError("invalid usage")
        usage = {k: usage[k] for k in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens") if k in usage}
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in usage.values()):
            raise ValueError("invalid usage tokens")
    return {"model": raw["model"], "answers": validated, "usage": usage}
