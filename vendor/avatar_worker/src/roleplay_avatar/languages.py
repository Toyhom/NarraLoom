"""Shared user-language contract for character creation and voice design."""

from typing import Literal

Locale = Literal["en", "zh-CN", "ja"]
LANGUAGES = {"en": "English", "zh-CN": "Chinese", "ja": "Japanese"}

VOICE_VARIATIONS = {
    "en": (
        "Natural face-to-face conversation, with varied emphasis and breathing pauses.",
        "Calm and warm, clear and relaxed, with natural sentence endings.",
        "Bright and friendly, with a gentle smile and an adult timbre.",
        "Gentle and intimate, softly voiced with conversational projection.",
        "Expressive storytelling, with varied emphasis and rhythm, speaking to one person.",
        "Clear and lively, with conversational rhythm and restrained playfulness.",
        "A slightly lower range, warm resonance and relaxed phonation.",
        "Delicate and articulate, with natural breath and melodic variation.",
    ),
    "zh-CN": (
        "自然口语，像面对面聊天，句子有自然的轻重音和呼吸停顿。",
        "略沉稳温润，清楚而放松，句尾自然收束。",
        "明亮轻快，富有亲和力，自然笑意，保持成年音色。",
        "舒缓亲近，柔和但不耳语，不要播音腔。",
        "有故事感，重音与节奏鲜明，自然地与一个人聊天。",
        "清爽利落，口语节奏，轻微俏皮但不夸张。",
        "略低的音域与温暖共鸣，发声放松。",
        "细腻明晰，保留自然气息和韵律变化。",
    ),
    "ja": (
        "向かい合って話すような自然な口調で、強弱と息継ぎをつける。",
        "落ち着いた温かい声で、明瞭かつリラックスし、語尾を自然に収める。",
        "明るく親しみやすく、微笑みを感じる大人の声。",
        "穏やかで親密な語り口で、柔らかく自然に声を届ける。",
        "物語を一人に語りかけるように、抑揚とリズムを豊かにつける。",
        "明快で軽やかな会話のリズムに、控えめな遊び心を加える。",
        "やや低めの音域と温かい共鳴で、力を抜いて発声する。",
        "繊細で明瞭に、自然な息遣いと抑揚の変化を保つ。",
    ),
}

VOICE_RECORDING = {
    "en": "Use natural conversational delivery and a clean, dry voice recording.",
    "zh-CN": "采用自然的对话节奏，录制干净清晰的人声。",
    "ja": "自然な会話の調子で、明瞭なドライ音声を録音する。",
}


def creation_language(locale: Locale):
    language = LANGUAGES[locale]
    return (
        f"Write display_name, tagline, persona, greeting, voice_design, voice_reason and voice_text in {language}. "
        "Keep explicitly supplied names. Write a coherent persona with identity, history, worldview, "
        "values, strengths, weaknesses, speech habits and relationship to the user, within 2400 characters. "
        "voice_text is a clean, natural, first-person sample for speech synthesis, between 40 and 160 characters. "
        "Describe an adult voice with pitch, resonance, texture, breath, articulation and pacing. "
        "Keep JSON field names and image_prompt in English."
    )
