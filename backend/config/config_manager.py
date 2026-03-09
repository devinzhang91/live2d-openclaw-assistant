"""
运行时配置管理器
管理 AI 性格、TTS 音色、语速等可动态调整的配置
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

_CONFIG_PATH = Path(__file__).parent / "app_config.json"
_PROMPT_PATH = Path(__file__).parent / "prompt.json"


class ConfigManager:
    """运行时配置管理器（单例）"""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._prompts: Dict[str, Any] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载配置"""
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        except Exception as e:
            print(f"[ConfigManager] 加载 app_config.json 失败: {e}")
            self._config = {
                "current_personality": "tianxinxiaomei",
                "tts": {"speed_ratio": 1.0, "volume_ratio": 1.0, "pitch_ratio": 1.0},
                "personalities": []
            }

        try:
            with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
                self._prompts = json.load(f)
        except Exception as e:
            print(f"[ConfigManager] 加载 prompt.json 失败: {e}")
            self._prompts = {}

    def _save(self):
        """将当前配置写回 JSON 文件"""
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ConfigManager] 保存 app_config.json 失败: {e}")

    # ====== 读取接口 ======

    def get_personalities(self) -> List[dict]:
        return self._config.get("personalities", [])

    def get_current_personality_id(self) -> str:
        return self._config.get("current_personality", "tianxinxiaomei")

    def get_current_personality(self) -> Optional[dict]:
        pid = self.get_current_personality_id()
        for p in self.get_personalities():
            if p["id"] == pid:
                return p
        personalities = self.get_personalities()
        return personalities[0] if personalities else None

    def get_current_voice_type(self) -> str:
        p = self.get_current_personality()
        if p:
            return p.get("voice_type", "zh_female_tianxinxiaomei_emo_v2_mars_bigtts")
        return "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"

    def get_speed_ratio(self) -> float:
        return float(self._config.get("tts", {}).get("speed_ratio", 1.0))

    def get_vad_speech_threshold(self) -> float:
        return float(self._config.get("vad_speech_threshold", 0.030))

    def get_vad_interrupt_tts(self) -> bool:
        return bool(self._config.get("vad_interrupt_tts", False))

    def get_system_prompt(self) -> str:
        pid = self.get_current_personality_id()
        return self._prompts.get(pid, {}).get(
            "system",
            "你是一个智能助手，请用简洁自然的口语回答，不要使用任何格式符号。"
        )

    def get_openclaw_config(self) -> dict:
        """获取 OpenClaw webhook 配置"""
        return self._config.get("openclaw", {
            "enabled": False,
            "base_url": "http://127.0.0.1:18789",
            "token": "",
            "agent_name": "Live2D",
            "timeout_seconds": 60,
        })

    def is_openclaw_enabled(self) -> bool:
        return bool(self.get_openclaw_config().get("enabled", False))

    def get_openclaw_base_url(self) -> str:
        return self.get_openclaw_config().get("base_url", "http://127.0.0.1:18789")

    def get_openclaw_token(self) -> str:
        return self.get_openclaw_config().get("token", "")

    def get_openclaw_agent_name(self) -> str:
        return self.get_openclaw_config().get("agent_name", "Live2D")

    def get_openclaw_timeout(self) -> int:
        return int(self.get_openclaw_config().get("timeout_seconds", 60))

    def get_openclaw_session_key(self) -> str:
        return self.get_openclaw_config().get("session_key", "")

    def get_settings_dict(self) -> dict:
        """返回前端所需的设置数据"""
        return {
            "current_personality": self.get_current_personality_id(),
            "speed_ratio": self.get_speed_ratio(),
            "vad_speech_threshold": self.get_vad_speech_threshold(),
            "vad_interrupt_tts": self.get_vad_interrupt_tts(),
            "personalities": self.get_personalities(),
            "openclaw": self.get_openclaw_config(),
        }

    # ====== 写入接口 ======

    def update_settings(
        self,
        personality_id: Optional[str] = None,
        speed_ratio: Optional[float] = None,
        vad_speech_threshold: Optional[float] = None,
        vad_interrupt_tts: Optional[bool] = None,
        openclaw: Optional[dict] = None,
    ):
        """更新设置并持久化"""
        if personality_id is not None:
            # 校验 personality_id 合法
            valid_ids = [p["id"] for p in self.get_personalities()]
            if personality_id in valid_ids:
                self._config["current_personality"] = personality_id
            else:
                raise ValueError(f"无效的 personality_id: {personality_id}")

        if speed_ratio is not None:
            if not (0.2 <= speed_ratio <= 3.0):
                raise ValueError("speed_ratio 必须在 0.2 ~ 3.0 之间")
            self._config.setdefault("tts", {})["speed_ratio"] = round(speed_ratio, 2)

        if vad_speech_threshold is not None:
            if not (0.005 <= vad_speech_threshold <= 0.15):
                raise ValueError("vad_speech_threshold 必须在 0.005 ~ 0.15 之间")
            self._config["vad_speech_threshold"] = round(vad_speech_threshold, 4)

        if vad_interrupt_tts is not None:
            self._config["vad_interrupt_tts"] = bool(vad_interrupt_tts)

        if openclaw is not None:
            current = self._config.setdefault("openclaw", {})
            if "enabled" in openclaw:
                current["enabled"] = bool(openclaw["enabled"])
            if "base_url" in openclaw:
                current["base_url"] = str(openclaw["base_url"]).rstrip("/")
            if "token" in openclaw:
                current["token"] = str(openclaw["token"])
            if "agent_name" in openclaw:
                current["agent_name"] = str(openclaw["agent_name"])
            if "timeout_seconds" in openclaw:
                current["timeout_seconds"] = int(openclaw["timeout_seconds"])

        self._save()


# 全局单例
config_manager = ConfigManager()
