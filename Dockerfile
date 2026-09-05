# Hugging Face Spaces (Docker SDK) 用イメージ
# openai-whisper が依存する torch の対応状況から Python 3.12 を使う
FROM python:3.12-slim

# ffmpeg は moviepy / pydub / whisper のすべてが必要とする
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
# HF Spaces の無料枠は CPU のみ。CUDA 版 torch は数 GB あるので CPU 版を明示的に入れる
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Whisper の base モデルをイメージに焼き込む（初回起動時のダウンロード待ちを無くす）
RUN python -c "import whisper; whisper.load_model('base')"

# HF Spaces は uid 1000 の非 root ユーザーで動く
RUN useradd -m -u 1000 user

# root で落としたモデルキャッシュを user から読める場所へ移す
RUN mkdir -p /home/user/.cache && \
    cp -r /root/.cache/whisper /home/user/.cache/whisper && \
    chown -R user:user /home/user/.cache

USER user

ENV PATH="/home/user/.local/bin:$PATH"
ENV HOME=/home/user
ENV XDG_CACHE_HOME=/home/user/.cache
# librosa が使う numba は書き込み可能なキャッシュ先が無いと起動時に落ちる
ENV NUMBA_CACHE_DIR=/tmp/numba_cache
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

COPY --chown=user . .

EXPOSE 7860

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
