#!/usr/bin/env python3

"""
drive_mind.py — the PC controller's side of her MIND mode (scripts/mind_drive.py on her).

Only on a PC that can think (mind.can_think(): x86, 8 GB+ RAM, GTX 1050 or better). Then this
signs in as her mind host (/unlock?pw=&ctl=1, her wheel lock left alone), keeps checking in on
/status?ctl=1 (remote_client.py), and while she's in MIND mode (9 here or on her) runs mind.py's
Mind with her body over the network:

  look         /status: her distance sensor, a wall, her wheel lock, the faces she sees, and
               (with a vision model in Ollama) what's straight ahead in her camera
  look_around  a move of its own: her camera's servo turns left, back and right (/look?at=), and
               mind.see() lists what's at each side. The next looks remember it for a minute.
               She's centred again before she drives
  act          /mind?act=&steps=, then /status until mindSteps is 0
  speak        mind.windows_wav() POSTed to /speak: her own speaker
"""

import os
import threading
import time

import requests

import mind

NAME = "KIDA00"
PERSONA = ("KIDA-00, the little KIDA: a small tracked robot with one camera on a neck that turns, "
           "so she can peek left and right without moving, a distance sensor in front and a speaker. "
           "Quick, cheeky and brave for her size, she loves music and faces, tries hard to keep up "
           "with her big sister KIDA-01, and always peeks around before she rolls somewhere new.")
VOICE = ("Microsoft Zira Desktop", 2, "high")
MOVES = {"fwd": "drive forward a little", "bwd": "drive backward a little",
         "left": "turn left on the spot", "right": "turn right on the spot",
         "look_around": "stand still and turn your camera left, ahead and right to see what's around you"}
SAFETY = ("she won't drive forward into anything within 15 cm, and won't move at all while her "
          "wheels are locked")
GOAL = "explore the room, say what you notice, and don't bump into anything"

PIN = os.environ.get("KIDA_PIN", "1234")   # a safety catch, not security
MOVE_TIMEOUT_S = 6.0
AROUND_FRESH_S = 60.0
LOOK_QUESTION = (
    "List the objects you can see in this picture, each with where it is in the picture and how big it "
    "looks. Answer JSON only: "
    '{"objects": [{"name": "...", "x": "left|centre|right", "size": "small|medium|large"}]}'
)


class DriveMind:
    def __init__(self, remote):
        self.remote = remote
        self.capable, self.why = False, "checking this PC..."
        self.around, self.around_t = None, 0.0
        self.mind = mind.Mind(NAME, PERSONA, MOVES, self.look, self.act, robot_say=self.robot_say,
                              voice=VOICE[0], rate=VOICE[1], pitch=VOICE[2], safety=SAFETY)
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        self.capable, self.why = mind.can_think()
        if not self.capable:
            print(f"MIND: not from this PC: {self.why}")
            return
        self.remote.mind_host = True   # remote_client polls /status?ctl=1 from now on
        while self.remote._running:
            try:
                r = requests.get(f"{self.remote.base_url}/unlock", params={"pw": PIN, "ctl": "1"}, timeout=2)
                if r.ok:
                    self.why = ""
                    print(f"MIND: this PC can drive her mind ({mind.CHOSEN_MODEL}): 9 for MIND mode")
                    return
                self.why = f"she said {r.status_code} to the PIN (KIDA_PIN, or her MotorPassword)"
                self.remote.mind_host = False
                return
            except requests.RequestException:
                time.sleep(3)   # not up yet

    # ── her body, over the network ──
    def _get(self, path, **kw):
        r = requests.get(f"{self.remote.base_url}{path}", timeout=kw.pop("timeout", 3), **kw)
        return r.json()

    def look(self):
        s = self._get("/status?ctl=1")
        senses = {"distance_ahead_cm": s.get("distance_cm"), "blocked": s.get("blocked"),
                  "wheels_locked": s.get("motor_lock"),
                  "faces": [f"{f.get('gender', '?')}, about {f.get('age', '?')}" for f in s.get("faces", [])]}
        if mind.vision_model() and self.remote.jpeg:
            view = mind.see(self.remote.jpeg, LOOK_QUESTION)
            senses["camera_sees_ahead"] = view.get("objects", view)
        if self.around and time.time() - self.around_t < AROUND_FRESH_S:
            senses["last_look_around"] = {"seconds_ago": int(time.time() - self.around_t), **self.around}
        return senses

    def look_around(self):
        if not mind.vision_model():
            return {"ok": False, "error": "no vision model on this PC (ollama pull gemma3:4b-it-qat)"}
        seen = {}
        for at, label in (("left", "left"), ("right", "right"), ("centre", "ahead")):   # ends centred
            r = requests.get(f"{self.remote.base_url}/look", params={"at": at}, timeout=5)
            if r.headers.get("Content-Type", "").startswith("image/"):
                view = mind.see(r.content, LOOK_QUESTION)
                seen[label] = view.get("objects", view)
            else:
                return {"ok": False, "error": r.json().get("error", r.status_code)}
        self.around, self.around_t = seen, time.time()
        return {"ok": True, "saw": seen}

    def act(self, move, steps):
        if move == "look_around":
            return self.look_around()
        r = self._get(f"/mind?act={move}&steps={steps}")
        if move == "stop" or not r.get("ok"):
            return r
        t0 = time.time()
        while time.time() - t0 < MOVE_TIMEOUT_S:
            time.sleep(0.3)
            s = self._get("/status?ctl=1")
            if not s.get("mindSteps"):
                return {"ok": True, "stopped_at_a_wall": bool(s.get("blocked"))}
        return {"ok": True, "note": "still moving"}

    def robot_say(self, text):
        try:
            wav = mind.windows_wav(text, *self.mind.voice)
            with open(wav, "rb") as f:
                r = requests.post(f"{self.remote.base_url}/speak", data=f.read(), timeout=10)
            os.remove(wav)
            return r.ok
        except Exception:
            return False   # mind.py says it on this PC instead

    # ── once a frame, from main.py ──
    def update(self, status):
        """Run the mind while she's in MIND mode; stop it when she leaves (any other mode ends MIND)."""
        ours = self.capable and self.remote.connected and status.get("mode") == "MIND"
        if ours and not self.mind.on and not (self.mind._thread and self.mind._thread.is_alive()):
            self.mind.start(goal=GOAL)
        elif not ours and self.mind.on:
            self.mind.on = False
            self.mind.state = "off"
