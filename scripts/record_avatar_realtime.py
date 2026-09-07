"""Record actual WebRTC output through OpenRealtime's production upload protocol."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import time
import wave
from pathlib import Path

import aiohttp
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder


async def record(args):
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    peer.addTransceiver("video", direction="recvonly")
    peer.addTransceiver("audio", direction="recvonly")
    recorder = MediaRecorder(str(args.output), format="mp4")
    tracks = []
    connected = asyncio.Event()

    @peer.on("track")
    def on_track(track):
        tracks.append(track.kind)
        recorder.addTrack(track)

    @peer.on("connectionstatechange")
    async def connection_changed():
        if peer.connectionState == "connected":
            connected.set()

    await peer.setLocalDescription(await peer.createOffer())
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as client:
        async with client.post(args.endpoint + "/offer", json={
            "sdp": peer.localDescription.sdp, "type": "offer", "avatar": args.avatar,
        }) as response:
            response.raise_for_status()
            answer = await response.json()
        await peer.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
        await asyncio.wait_for(connected.wait(), 20)
        await recorder.start()
        start = time.monotonic()
        evidence = {"endpoint": args.endpoint, "avatar": args.avatar, "tracks": tracks,
                    "session_id": answer["sessionid"], "uploads": [], "metrics": []}
        sender: asyncio.Task | None = None
        try:
            await asyncio.sleep(1)
            for audio in args.audio:
                data = audio.read_bytes()
                with wave.open(str(audio)) as source:
                    duration = source.getnframes() / source.getframerate()
                generation = len(evidence["uploads"])
                upload = {"file": str(audio), "at_seconds": time.monotonic() - start,
                          "duration_seconds": duration, "chunk_ms": args.chunk_ms}
                evidence["uploads"].append(upload)

                async def send_audio(data=data, generation=generation, upload=upload, audio=audio):
                    with wave.open(io.BytesIO(data)) as source:
                        params = source.getparams()
                        raw = source.readframes(source.getnframes())
                    chunk_bytes = max(2, round(args.chunk_ms * params.framerate / 1000) * 2) if args.chunk_ms else len(raw)
                    pieces = [raw[i:i + chunk_bytes] for i in range(0, len(raw), chunk_bytes)]
                    for sequence, piece in enumerate(pieces):
                        packet = io.BytesIO()
                        with wave.open(packet, "wb") as target:
                            target.setparams(params)
                            target.writeframes(piece)
                        form = aiohttp.FormData()
                        form.add_field("sessionid", answer["sessionid"])
                        form.add_field("generation", str(generation))
                        form.add_field("sequence", str(sequence))
                        form.add_field("final", "1" if sequence == len(pieces) - 1 else "0")
                        form.add_field("file", packet.getvalue(), filename=audio.name, content_type="audio/wav")
                        async with client.post(args.endpoint + "/humanaudio", data=form) as response:
                            response.raise_for_status()
                            if (await response.json()).get("code") != 0:
                                raise RuntimeError("Audio upload was not accepted")
                        if sequence < len(pieces) - 1:
                            await asyncio.sleep(len(piece) / 2 / params.framerate * args.pace)
                    upload["last_chunk_at_seconds"] = time.monotonic() - start

                sender = asyncio.create_task(send_audio())
                deadline = time.monotonic() + duration * 2 + 15
                interrupt_at = (time.monotonic() + args.interrupt_after) if generation == 0 and args.interrupt_after else None
                while True:
                    await asyncio.sleep(0.5)
                    async with client.get(args.endpoint + "/health") as response:
                        health = await response.json()
                        evidence["metrics"].append(health)
                    if sender.done():
                        await sender
                    metrics = health["sessions"][answer["sessionid"]]
                    if metrics["failure"]:
                        raise RuntimeError(metrics["failure"])
                    if interrupt_at is not None and time.monotonic() >= interrupt_at:
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
                        async with client.post(args.endpoint + "/interrupt_talk", json={
                            "sessionid": answer["sessionid"], "generation": generation,
                        }) as response:
                            response.raise_for_status()
                        upload["interrupted_at_seconds"] = time.monotonic() - start
                        break
                    if metrics.get("speeches", {}).get(str(generation), {}).get("state") == "completed":
                        await sender
                        await asyncio.sleep(1)
                        async with client.get(args.endpoint + "/health") as final_response:
                            evidence["metrics"].append(await final_response.json())
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("The renderer did not finish the complete utterance")
            evidence["wall_seconds"] = time.monotonic() - start
        finally:
            if sender is not None:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            await recorder.stop()
            await peer.close()
            args.output.with_suffix(".json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"output": str(args.output), "wall_seconds": evidence["wall_seconds"],
                      "health": evidence["metrics"][-1]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8010")
    parser.add_argument("--avatar", required=True)
    parser.add_argument("--audio", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-ms", type=int, default=0)
    parser.add_argument("--pace", type=float, default=0.5)
    parser.add_argument("--interrupt-after", type=float)
    args = parser.parse_args()
    if not 0 <= args.chunk_ms <= 2000 or not 0 <= args.pace <= 2:
        parser.error("chunk-ms must be 0..2000 and pace must be 0..2")
    if args.interrupt_after is not None and args.interrupt_after <= 0:
        parser.error("interrupt-after must be positive")
    asyncio.run(record(args))
