from dotenv import load_dotenv
load_dotenv() # .env dosyasındaki değişkenleri yükler

from flask import Flask, jsonify, render_template, request, session, redirect, url_for # session, redirect, url_for eklendi
import os # os modülü eklendi
from spotify import (
    get_album,
    get_all_trackids,
    get_track,
    get_play,
    check_regex,
    query_spotify,
    format_duration,
    get_spotify_oauth,          # Yeni eklendi
    get_currently_playing_track, # Yeni eklendi
    get_lyrics_from_api,        # Şarkı sözü için eklendi
    get_chatgpt_interpretation  # ChatGPT yorumu için eklendi
)

app = Flask(__name__)
# YENİ: Flask session'ları için secret key. Güvenli bir yerden alınmalı.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your_default_secret_key_please_change_this") # Ortam değişkeninden veya varsayılan


@app.route("/")
def index():
    # YENİ: Ana sayfaya "Now Playing" linki için bir değişken ekleyebiliriz
    return render_template("index.html", now_playing_available=True)


@app.route("/spotify", methods=["POST"])
def download():
    if not request.form:
        return "No arguments provided"
    url_type, id = check_regex(request.form.get("url"))
    if url_type == "album":
        return render_template("spotify.html", data=get_album(id), types="album")
    elif url_type == "track":
        return render_template("spotify.html", data=get_track(id), types="track")
    elif url_type == "playlist":
        return render_template("spotify.html", data=get_play(id), types="playlist")
    else:

        return (
            render_template(
                "index.html", error="Invalid URL...Please check the URL and try again"
            ),
            400,
        )


@app.route("/api/search")
def api():
    q = request.args.get("q")
    return query_spotify(q) if q else "No arguments provided"


@app.get("/api/getalltracks")
def get_all_tracks():
    album_id = request.args.get("id")
    album = bool(request.args.get("album"))
    if album_id:
        return jsonify(get_all_trackids(album_id, album))
    else:
        return "No arguments provided", 400
    
@app.get("/api/tracks/<string:track_id>")
def track_details(track_id: str):
    if track_id:
        try:
            return jsonify(get_track(track_id))
        except Exception as e:
            return "Invalid Track ID", 400
    else:
        return "No arguments provided", 400

# YENİ: Spotify'a giriş için route
@app.route("/login_spotify")
def login_spotify():
    sp_oauth = get_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


# YENİ: Spotify'dan callback route'u
@app.route("/callback")
def callback():
    sp_oauth = get_spotify_oauth()
    code = request.args.get('code')
    error = request.args.get('error')

    if error:
        app.logger.error(f"Spotify authorization failed: {error}")
        return render_template("index.html", error=f"Spotify yetkilendirmesi başarısız: {error}"), 400

    if code:
        try:
            token_info = sp_oauth.get_access_token(code, check_cache=False) 
            session["spotify_token_info"] = token_info 
        except Exception as e:
            app.logger.error(f"Error getting or caching token: {e}")
            return render_template("index.html", error=f"Spotify'dan token alınırken hata oluştu. Lütfen tekrar deneyin."), 500
        return redirect(url_for('now_playing'))
    else:
        return render_template("index.html", error="Spotify yetkilendirmesi sırasında bilinmeyen bir sorun oluştu."), 400


# YENİ: Anlık çalınan şarkıyı göstermek için route
@app.route("/now-playing")
def now_playing():
    token_info = session.get("spotify_token_info")
    sp_oauth = get_spotify_oauth()

    if not token_info:
        app.logger.info("No token in session, redirecting to login_spotify.")
        return redirect(url_for('login_spotify'))

    if not sp_oauth.validate_token(token_info):
        if 'refresh_token' in token_info:
            try:
                refreshed_token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
                session["spotify_token_info"] = refreshed_token_info
                token_info = refreshed_token_info
                app.logger.info("Spotify token refreshed and updated in session.")
            except Exception as e:
                app.logger.error(f"Error refreshing Spotify token from session: {e}. Redirecting to login.")
                session.clear()
                return redirect(url_for('login_spotify', error="Oturumunuz yenilenemedi, lütfen tekrar giriş yapın."))
        else:
            app.logger.warning("Invalid token in session and no refresh token found. Redirecting to login.")
            session.clear()
            return redirect(url_for('login_spotify', error="Geçersiz oturum, lütfen tekrar giriş yapın."))
    
    current_track_info = get_currently_playing_track(sp_oauth)

    if current_track_info and current_track_info.get('id'):
        lyrics = get_lyrics_from_api(current_track_info['id'])
        current_track_info["lyrics"] = lyrics if lyrics else "Şarkı sözleri bulunamadı veya alınamadı."

        chatgpt_commentary = "Şarkı sözleri için henüz bir yorum oluşturulmadı veya alınamadı."
        if lyrics and current_track_info.get('name') and current_track_info.get('artist'):
            chatgpt_commentary = get_chatgpt_interpretation(lyrics, current_track_info['name'], current_track_info['artist'])
        
        current_track_info["chatgpt_commentary"] = chatgpt_commentary
        return render_template("now_playing.html", track=current_track_info, token_available=True)
    elif current_track_info: # Şarkı bilgisi var ama ID yoksa (beklenmedik durum)
        current_track_info["lyrics"] = "Şarkı ID'si alınamadığı için sözler getirilemedi."
        return render_template("now_playing.html", track=current_track_info, token_available=True)
    else:
        no_playback_message = "Şu anda Spotify'da bir şey çalmıyor veya bilgi alınamadı. Lütfen Spotify'da bir şarkı başlattığınızdan emin olun."
        return render_template("now_playing.html", message=no_playback_message, token_available=bool(token_info))


app.add_template_filter(format_duration)
@app.route('/analyze-lyrics', methods=['POST'])
def analyze_lyrics():
    data = request.get_json()
    lyrics = data.get('lyrics', '')
    track_name = data.get('track_name', 'Bilinmeyen Şarkı')
    artist_name = data.get('artist_name', 'Bilinmeyen Sanatçı')
    
    if not lyrics:
        return jsonify({'success': False, 'error': 'Şarkı sözleri bulunamadı.'})
    try:
        analysis = get_chatgpt_interpretation(lyrics, track_name, artist_name)
        return jsonify({'success': True, 'analysis': analysis})
    except Exception as e:
        print(f"Lyrics analiz hatası: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
