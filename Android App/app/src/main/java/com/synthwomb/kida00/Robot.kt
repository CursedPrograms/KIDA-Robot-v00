package com.synthwomb.kida00

import org.json.JSONObject
import java.util.Locale

// What KIDA-00 takes: the same calls as RITA and her PC controller.
class Robot(private val http: Http) : RobotApi {
    private fun n(v: Float) = String.format(Locale.ROOT, "%.2f", v)

    private fun send(command: String) = http.post("/command", "{\"command\":\"$command\"}")

    override fun connect(pin: String) {
        http.get("/motorlockOff?pw=$pin")
        send("_mode_user")
        send("scheme_wasd")
    }
    override fun drive(forward: Float, side: Float, turn: Float) {
        send("drive:${n((forward - turn).coerceIn(-1f, 1f))}:${n((forward + turn).coerceIn(-1f, 1f))}")
    }
    override fun stop() { send("stop") }
    override fun tiles(s: JSONObject) = listOf(
        "Front" to Tiles.cm(s.opt("distance_cm")),
        "Mode" to s.optString("mode", "--"),
        "Speed" to s.optString("speed", "--"),
        "Moving" to if (s.optBoolean("moving")) "yes" else "no",
        "Music" to s.optString("music", "--"),
    )

    override val buttons = listOf(
        "USER" to { send("_mode_user"); Unit },
        "AUTO" to { send("_mode_autonomous"); Unit },
        "HELLO" to { send("hello"); Unit },
        "DANCE" to { send("dance"); Unit },
        "PHOTO" to { send("photo"); Unit },
        "MUSIC" to { send("music_toggle"); Unit },
        "LOCK" to { http.get("/motorlockOn"); Unit },
    )
}
