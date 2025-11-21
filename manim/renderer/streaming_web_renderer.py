"""
Streaming Web Renderer - Real-time frame delivery as they're generated
Perfect for React Native webviews and live preview
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Callable

import numpy as np
from manim.camera.moving_camera import MovingCamera
from manim.renderer.cairo_renderer import CairoRenderer
from manim.mobject.types.vectorized_mobject import VMobject
from manim.utils.color import ManimColor
from manim import config, logger


class StreamingWebCamera(MovingCamera):
    """Camera that streams frames as they're generated with MovingCamera support"""

    def __init__(self, *args, on_frame_callback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.frame_data = []
        self.on_frame_callback = on_frame_callback
        self.frame_count = 0

    def reset_frame_data(self):
        self.frame_data = []

    def display_multiple_vectorized_mobjects(self, vmobjects: list[VMobject], pixel_array) -> None:
        """Capture VMobject data"""
        added_count = 0
        skipped_count = 0
        transparent_count = 0

        for vm in vmobjects:
            points = vm.points.tolist()

            # Skip mobjects with no points - they're invisible
            if not points or len(points) == 0:
                skipped_count += 1
                continue

            fill_color = vm.fill_color
            if isinstance(fill_color, ManimColor):
                fill_color = fill_color.to_hex()

            stroke_color = vm.stroke_color
            if isinstance(stroke_color, ManimColor):
                stroke_color = stroke_color.to_hex()

            fill_opacity = float(vm.fill_opacity)
            stroke_width = float(vm.stroke_width)
            stroke_opacity = float(vm.stroke_opacity)

            # IMPORTANT: Use get_fill_rgbas() and get_stroke_rgbas() like Cairo does
            # to get the actual colors/opacities used for rendering
            try:
                fill_rgbas = vm.get_fill_rgbas()
                if len(fill_rgbas) > 0:
                    # Use the alpha channel from the RGBA array (4th component)
                    actual_fill_opacity = float(fill_rgbas[0][3])
                    if actual_fill_opacity != fill_opacity:
                        fill_opacity = actual_fill_opacity
            except Exception:
                pass  # Fall back to fill_opacity property

            try:
                stroke_rgbas = vm.get_stroke_rgbas()
                if len(stroke_rgbas) > 0:
                    actual_stroke_opacity = float(stroke_rgbas[0][3])
                    if actual_stroke_opacity != stroke_opacity:
                        stroke_opacity = actual_stroke_opacity
            except Exception:
                pass  # Fall back to stroke_opacity property

            # Debug: track transparent mobjects
            if fill_opacity == 0.0 and (stroke_width == 0.0 or stroke_opacity == 0.0):
                transparent_count += 1

            self.frame_data.append({
                "type": "VMobject",
                "points": points,
                "fill_color": fill_color,
                "fill_opacity": fill_opacity,
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "stroke_opacity": stroke_opacity,
            })
            added_count += 1

        if skipped_count > 0 or transparent_count > 0:
            logger.debug(f"  Added {added_count} mobjects ({transparent_count} appear transparent), skipped {skipped_count} with no points")

    def display_multiple_image_mobjects(self, image_mobjects, pixel_array):
        pass

    def display_multiple_point_cloud_mobjects(self, pmobjects, pixel_array):
        pass


class StreamingWebRenderer(CairoRenderer):
    """
    Streaming renderer that yields frames as they're generated.
    Perfect for React Native integration and live preview!

    Usage:
        renderer = StreamingWebRenderer(on_frame=my_callback)
        # Callback receives frames in real-time as they're generated
    """

    def __init__(self, *args, on_frame_callback=None, **kwargs):
        self.on_frame_callback = on_frame_callback
        super().__init__(
            camera_class=StreamingWebCamera,
            skip_animations=False,
            *args,
            **kwargs
        )
        self.camera.on_frame_callback = on_frame_callback
        self.all_frames = []
        self.stream_file = None

    def init_scene(self, scene) -> None:
        config.write_to_movie = False

        # Create streaming HTML file
        output_dir = config.media_dir
        os.makedirs(output_dir, exist_ok=True)
        stream_path = os.path.join(output_dir, "stream.html")

        # Write initial HTML with live streaming capability
        with open(stream_path, 'w') as f:
            f.write(self._get_streaming_html_header())

        self.stream_file = stream_path
        logger.info(f"🔴 LIVE streaming to {stream_path}")

        super().init_scene(scene)

    def render(self, scene, time, moving_mobjects=None):
        """Render frame and immediately stream it"""
        self.camera.reset_frame_data()

        # Capture frame - extract ALL family members to include text submobjects
        from manim.utils.family import extract_mobject_family_members
        all_mobjects = extract_mobject_family_members(
            scene.mobjects,
            only_those_with_points=True,
        )

        # Filter to VMobjects (includes SVGMobjects like MathTex)
        vmobjects = [m for m in all_mobjects if isinstance(m, VMobject)]

        # Debug: log mobject count every 30 frames
        frame_index = len(self.all_frames)
        if frame_index % 30 == 0:
            logger.info(f"Frame {frame_index}: {len(scene.mobjects)} scene mobjects, {len(vmobjects)} VMobjects captured")

        self.camera.display_multiple_vectorized_mobjects(vmobjects, None)

        # Debug: log actual frame_data length
        if frame_index % 30 == 0:
            logger.info(f"  Frame data contains {len(self.camera.frame_data)} mobjects with points")

        # Capture camera frame transform (for zooming/panning)
        camera_transform = {
            "height": float(self.camera.frame.height),
            "width": float(self.camera.frame.width),
            "center": self.camera.frame.get_center().tolist()
        }

        # Create frame data
        frame_data = {
            "time": time,
            "frame_index": len(self.all_frames),
            "mobjects": self.camera.frame_data,
            "camera": camera_transform
        }

        self.all_frames.append(frame_data)

        # STREAM IT IMMEDIATELY!
        self._stream_frame(frame_data)

        # Also call user callback if provided
        if self.on_frame_callback:
            self.on_frame_callback(frame_data)

    def _stream_frame(self, frame_data):
        """Append frame to HTML file in real-time"""
        if not self.stream_file:
            return

        # Append frame data to JavaScript array
        frame_js = json.dumps(frame_data, separators=(',', ':'))

        with open(self.stream_file, 'a') as f:
            f.write(f"\n<script>if(window.addFrame)window.addFrame({frame_js});</script>")

    def update_frame(self, scene, mobjects=None, **kwargs):
        """Skip pixel rendering"""
        pass

    def freeze_current_frame(self, duration: float) -> None:
        """Handle wait periods"""
        dt = 1 / self.camera.frame_rate
        num_frames = int(duration / dt)

        if self.all_frames:
            last_frame = self.all_frames[-1]
            frame_data = last_frame["mobjects"]
            camera_data = last_frame.get("camera", {
                "height": 8.0,
                "width": 8.0 * (config.pixel_width / config.pixel_height),
                "center": [0, 0, 0]
            })

            for i in range(num_frames):
                self.time += dt
                new_frame = {
                    "time": self.time,
                    "frame_index": len(self.all_frames),
                    "mobjects": frame_data,
                    "camera": camera_data
                }
                self.all_frames.append(new_frame)
                self._stream_frame(new_frame)

    def scene_finished(self, scene):
        """Finalize the streaming HTML"""
        if not self.stream_file:
            return

        # Write closing HTML
        with open(self.stream_file, 'a') as f:
            f.write(self._get_streaming_html_footer())

        num_frames = len(self.all_frames)
        logger.info(f"✅ Streaming complete: {num_frames} frames")
        logger.info(f"   Open {self.stream_file} in browser!")

    def _get_streaming_html_header(self):
        """HTML that loads and starts playing frames as they arrive"""
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>ManimLive - LIVE Streaming</title>
    <meta charset="utf-8">
    <style>
        body {{ margin: 0; background: #111; color: #eee; font-family: monospace; }}
        canvas {{ display: block; margin: 20px auto; background: #000; border: 2px solid #333; }}
        #controls {{ text-align: center; padding: 10px; }}
        #status {{ text-align: center; padding: 5px; font-size: 12px; color: #0f0; }}
        input[type=range] {{ width: 80%; }}
        .live {{ color: #f00; animation: blink 1s infinite; }}
        @keyframes blink {{ 0%, 50% {{ opacity: 1; }} 51%, 100% {{ opacity: 0.3; }} }}
    </style>
</head>
<body>
    <div id="status">
        <span class="live">● LIVE</span> Streaming frames as they generate...
        <span id="frameCount">0 frames</span>
    </div>
    <canvas id="canvas"></canvas>
    <div id="controls">
        <input type="range" id="slider" min="0" max="0" value="0" step="1">
        <div id="timeDisplay">0.00s</div>
        <button id="playPause">Pause</button>
        <button id="restart">Restart</button>
    </div>
    <script>
        const canvas = document.getElementById('canvas');
        const ctx = canvas.getContext('2d');
        const slider = document.getElementById('slider');
        const timeDisplay = document.getElementById('timeDisplay');
        const playPauseBtn = document.getElementById('playPause');
        const restartBtn = document.getElementById('restart');
        const frameCountEl = document.getElementById('frameCount');

        let frames = [];
        let currentFrame = 0;
        let isPlaying = true;
        let lastFrameTime = performance.now();

        canvas.width = {config.pixel_width};
        canvas.height = {config.pixel_height};

        function resize() {{
            const scale = Math.min(window.innerWidth / canvas.width, (window.innerHeight - 150) / canvas.height);
            canvas.style.width = (canvas.width * scale) + 'px';
            canvas.style.height = (canvas.height * scale) + 'px';
        }}
        window.addEventListener('resize', resize);
        resize();

        // Called by streaming script tags as frames generate
        window.addFrame = function(frame) {{
            frames.push(frame);
            slider.max = frames.length - 1;
            frameCountEl.textContent = frames.length + ' frames';

            // Auto-play new frames as they arrive
            if (isPlaying && currentFrame >= frames.length - 2) {{
                currentFrame = frames.length - 1;
                renderFrame(currentFrame);
            }}

            // Notify React Native
            if (window.ReactNativeWebView) {{
                window.ReactNativeWebView.postMessage(JSON.stringify({{
                    type: 'frame_added',
                    frameIndex: frames.length - 1,
                    totalFrames: frames.length
                }}));
            }}
        }};

        function renderFrame(index) {{
            const frame = frames[index];
            if (!frame) return;

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Get camera transform (with defaults for backward compatibility)
            const camera = frame.camera || {{
                height: 8.0,
                width: 8.0 * (canvas.width / canvas.height),
                center: [0, 0, 0]
            }};

            frame.mobjects.forEach(mob => {{
                if (mob.type === "VMobject") {{
                    drawVMobject(mob, camera);
                }}
            }});

            timeDisplay.textContent = frame.time.toFixed(2) + 's';
            slider.value = index;
            currentFrame = index;
        }}

        function drawVMobject(mob, camera) {{
            if (!mob.points || mob.points.length < 4) return;

            const pts = mob.points;
            const frameHeight = camera.height;
            const frameWidth = camera.width;
            const [centerX, centerY, centerZ] = camera.center;

            // Transform from scene coordinates to canvas coordinates
            const toCanvasX = (x) => ((x - centerX) + frameWidth/2) / frameWidth * canvas.width;
            const toCanvasY = (y) => (frameHeight/2 - (y - centerY)) / frameHeight * canvas.height;

            // Match Cairo's tolerance for detecting discontinuities
            const rtol = 1e-5;
            const atol = 1e-6;
            const pointsEqual = (p1, p2) => {{
                if (!p1 || !p2) return false;
                return Math.abs(p1[0] - p2[0]) <= atol + rtol * Math.abs(p2[0]) &&
                       Math.abs(p1[1] - p2[1]) <= atol + rtol * Math.abs(p2[1]);
            }};

            // More forgiving tolerance for closing paths (Manim shapes don't close perfectly)
            const pointsClose = (p1, p2) => {{
                if (!p1 || !p2) return false;
                const dx = p1[0] - p2[0];
                const dy = p1[1] - p2[1];
                return Math.sqrt(dx*dx + dy*dy) < 0.15;
            }};

            // Find subpath break indices (matching Manim's gen_subpaths_from_points_2d)
            const breakIndices = [0];
            for (let n = 4; n < pts.length; n += 4) {{
                // Check if points[n-1] != points[n] (discontinuity between segments)
                if (!pointsEqual(pts[n-1], pts[n])) {{
                    breakIndices.push(n);
                }}
            }}
            breakIndices.push(pts.length);

            // Render each subpath separately
            for (let subIdx = 0; subIdx < breakIndices.length - 1; subIdx++) {{
                const start = breakIndices[subIdx];
                const end = breakIndices[subIdx + 1];

                if (end - start < 4) continue; // Need at least one curve

                ctx.beginPath();
                ctx.moveTo(toCanvasX(pts[start][0]), toCanvasY(pts[start][1]));

                // Draw all curves in this subpath
                for (let i = start; i + 3 < end; i += 4) {{
                    const h1 = pts[i+1];
                    const h2 = pts[i+2];
                    const nextAnchor = pts[i+3];

                    if (!h1 || !h2 || !nextAnchor) continue;

                    ctx.bezierCurveTo(
                        toCanvasX(h1[0]), toCanvasY(h1[1]),
                        toCanvasX(h2[0]), toCanvasY(h2[1]),
                        toCanvasX(nextAnchor[0]), toCanvasY(nextAnchor[1])
                    );
                }}

                // Close subpath if start and end are close
                if (pointsClose(pts[start], pts[end - 1])) {{
                    ctx.closePath();
                }}

                // Fill and stroke this subpath
                ctx.fillStyle = mob.fill_color || '#FFFFFF';
                ctx.globalAlpha = mob.fill_opacity || 0;
                ctx.fill('evenodd');

                if ((mob.stroke_width || 0) > 0) {{
                    ctx.strokeStyle = mob.stroke_color || '#FFFFFF';
                    ctx.lineWidth = mob.stroke_width;
                    ctx.lineJoin = 'miter';
                    ctx.lineCap = 'butt';
                    ctx.miterLimit = 10;
                    ctx.globalAlpha = mob.stroke_opacity || 0;
                    ctx.stroke();
                }}
            }}

            ctx.globalAlpha = 1.0;
        }}

        slider.addEventListener('input', (e) => {{
            currentFrame = parseInt(e.target.value);
            renderFrame(currentFrame);
        }});

        playPauseBtn.addEventListener('click', () => {{
            isPlaying = !isPlaying;
            playPauseBtn.textContent = isPlaying ? 'Pause' : 'Play';
            if (isPlaying) {{
                lastFrameTime = performance.now();
                loop();
            }}
        }});

        restartBtn.addEventListener('click', () => {{
            currentFrame = 0;
            renderFrame(0);
        }});

        function loop() {{
            if (!isPlaying) return;

            const now = performance.now();
            const elapsed = now - lastFrameTime;

            // 60fps playback
            if (elapsed >= 16.67) {{
                lastFrameTime = now;

                if (currentFrame < frames.length - 1) {{
                    currentFrame++;
                    renderFrame(currentFrame);
                }} else if (frames.complete) {{
                    isPlaying = false;
                    playPauseBtn.textContent = 'Play';
                    return;
                }}
            }}

            requestAnimationFrame(loop);
        }}

        // Start playback loop
        loop();

        // Notify React Native that streaming started
        if (window.ReactNativeWebView) {{
            window.ReactNativeWebView.postMessage(JSON.stringify({{
                type: 'streaming_started',
                timestamp: Date.now()
            }}));
        }}
    </script>
"""

    def _get_streaming_html_footer(self):
        """Mark streaming as complete - SAFE version"""
        return """
    <script>
        frames.complete = true;
        const statusEl = document.getElementById('status');
        statusEl.textContent = '✓ COMPLETE ' + frames.length + ' frames loaded';
        statusEl.style.color = '#0f0';

        // Notify React Native
        if (window.ReactNativeWebView) {
            window.ReactNativeWebView.postMessage(JSON.stringify({
                type: 'streaming_complete',
                totalFrames: frames.length,
                timestamp: Date.now()
            }));
        }
    </script>
</body>
</html>
"""
