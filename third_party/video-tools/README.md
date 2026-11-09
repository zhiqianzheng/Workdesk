# Video decoding components

Workdesk invokes FFmpeg as a separate, bounded process to sample local received MP4 attachments. It does not fetch remote video URLs or log into Channels.

The distribution includes the platform wheel for imageio-ffmpeg 0.6.0, its Python wrapper license and bundled FFmpeg executable. Linux staging verifies the wheel SHA-256 against PyPI metadata; Windows uses the pinned wheel dependency. Wheel notices are retained in the Linux `_vendor` directory and collected with the Windows package.

- Wrapper, release and build recipes: https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0
- Platform executable origins: https://github.com/imageio/imageio-ffmpeg/blob/v0.6.0/tasks.py
- Linux executable: FFmpeg 7.0.2; FFmpeg corresponding source release: https://ffmpeg.org/releases/ffmpeg-7.0.2.tar.xz
- FFmpeg source and license details: https://ffmpeg.org/legal.html
- The GPLv3 text accompanying this component is in COPYING.GPLv3. Consult each executable's `-version` and `-L` output for its build configuration and notices.

Sampling is visual only: up to four frames from a maximum three-minute, 50-MB received MP4. This is not full temporal coverage or speech transcription.
