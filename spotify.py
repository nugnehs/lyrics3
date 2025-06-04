import re
import requests
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth # SpotifyOAuth eklendi
import os
from openai import OpenAI # Added for ChatGPT integration

from dotenv import load_dotenv
load_dotenv()

cid = os.getenv("SPOTIFY_CLIENT_ID")
secret = os.getenv("SPOTIFY_CLIENT_SECRET")
# Yeni: Redirect URI'yi ortam değişkeninden al
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:5000/callback") # Varsayılan eklendi

# Bu sp nesnesi genel API çağrıları için kalabilir (Client Credentials Flow)
client_credentials_manager = SpotifyClientCredentials(
    client_id=cid, client_secret=secret
)
sp_public = spotipy.Spotify(client_credentials_manager=client_credentials_manager) # Yeniden adlandırıldı

REGEX = r"^(?:spotify:(track|album|playlist):|https:\/\/[a-z]+\.spotify\.com\/(track|playlist|album)\/)(.\w+)?.*$"
SHORT_URL_REGEX = r'window.top.location = validateProtocol\("(\S+)"\);'

# YENİ: SpotifyOAuth nesnesi oluşturmak için yardımcı fonksiyon
def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=cid,
        client_secret=secret,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope="user-read-currently-playing" # Gerekli yetki kapsamı
    )

# YENİ: Anlık çalınan şarkıyı getiren fonksiyon
def get_currently_playing_track(auth_manager):
    """
    Yetkilendirilmiş bir Spotify nesnesi kullanarak o an çalınan şarkıyı alır.
    """
    # Token'ın geçerli olup olmadığını kontrol et, gerekirse yenilemeye çalışır.
    # Eğer cache'de token yoksa veya yenilenemiyorsa get_cached_token None dönebilir.
    if not auth_manager.validate_token(auth_manager.get_cached_token()):
         # Eğer token geçerli değilse ve yenilenemiyorsa, None dönebiliriz
         # veya kullanıcıyı yeniden login'e yönlendirmek için bir işaretçi dönebiliriz.
         # Şimdilik None dönüyoruz, bu Flask tarafında handle edilecek.
        return None

    sp_user = spotipy.Spotify(auth_manager=auth_manager)
    current_track = sp_user.current_user_playing_track()
    if current_track and current_track.get('item'): # .get() ile daha güvenli erişim
        item = current_track['item']
        track_info = {
            "name": item.get('name'),
            "artist": ", ".join([artist.get('name', 'Bilinmeyen Sanatçı') for artist in item.get('artists', [])]),
            "album": item.get('album', {}).get('name', 'Bilinmeyen Albüm'),
            "image_url": item.get('album', {}).get('images', [{}])[0].get('url') if item.get('album', {}).get('images') else None,
            "id": item.get('id'),
            "is_playing": current_track.get('is_playing'),
            "progress_ms": current_track.get('progress_ms'),
            "duration_ms": item.get('duration_ms'),
        }
        return track_info
    return None


def get_album(album_id):
    album_data = sp_public.album(album_id) # sp_public kullanıldı
    album_data["artists"] = ",".join(
        [artist["name"] for artist in album_data["artists"]]
    )
    return {
        "name": album_data["name"],
        "id": album_id,
        "artist": album_data["artists"],
        "total_tracks": album_data["total_tracks"],
        "release_date": album_data["release_date"],
        "label": album_data["label"],
        "image": album_data["images"][0]["url"],
        "tracks": album_data["tracks"]["items"],
    }


def get_track(track_id):
    track_data = sp_public.track(track_id) # sp_public kullanıldı
    track_data["artist"] = ",".join(
        [artist["name"] for artist in track_data["artists"]]
    )
    return {
        "track_name": track_data["name"],
        "track_id": track_id,
        "track_artist": track_data["artist"],
        "track_album": track_data["album"]["name"],
        "image": track_data["album"]["images"][0]["url"],
        "track_explicit": "[E]" if track_data["explicit"] else "Not Explicit",
        "track_release_date": track_data["album"]["release_date"],
        "track_popularity": track_data["popularity"],
        "track_number": track_data["track_number"],
        "track_duration": format_duration(track_data["duration_ms"]),
    }


def get_play(play_id):
    play_data = sp_public.playlist(play_id) # sp_public kullanıldı
    play_data["owner"] = play_data["owner"]["display_name"]
    play_data["total_tracks"] = play_data["tracks"]["total"]
    play_data["collaborative"] = (
        "Collaborative" if play_data["collaborative"] else "Not Collaborative"
    )
    return {
        "name": play_data["name"],
        "id": play_id,
        "owner": play_data["owner"],
        "total_tracks": play_data["total_tracks"],
        "desc": play_data["description"] or "No Description",
        "followers": play_data["followers"]["total"],
        "image": play_data["images"][0]["url"],
        "tracks": play_data["tracks"]["items"],
    }


def check_regex(url):
    url = requests.get(url, allow_redirects=True).url
    if "spotify.link" in url or "spotify.app.link" in url:
        req = requests.get(url, allow_redirects=True).text
        match = re.search(SHORT_URL_REGEX, req)
        if match:
            url = match[1]
    match = re.match(REGEX, url)
    if not match:
        payload = {"url": url, "country": "IN"}
        req = requests.post("https://songwhip.com/api/songwhip/create", json=payload)
        print(req.json())
        if req.status_code != 200:
            return None, None
        link = req.json()["data"]["item"]["links"]["spotify"][0]["link"]
        match = re.match(REGEX, link)
    if match[2]:
        return match[2], match[3]
    elif match[1]:
        return match[1], match[3]
    else:
        return None, None


def query_spotify(q=None, type="track,album,playlist"):
    data = sp_public.search(q=q, type=type, limit=1) # sp_public kullanıldı
    response = []
    if data["tracks"]["items"]:
        response.append(
            {
                "name": data["tracks"]["items"][0]["name"],
                "type": "track",
                "image": data["tracks"]["items"][0]["album"]["images"][0]["url"], # Yazım hatası düzeltildi: image;: -> image:
            }
        )
    if data["albums"]["items"]:
        response.append(
            {
                "name": data["albums"]["items"][0]["name"],
                "type": "album",
                "image": data["albums"]["items"][0]["images"][0]["url"],
            }
        )
    if data["playlists"]["items"]:
        response.append(
            {
                "name": data["playlists"]["items"][0]["name"],
                "type": "playlist",
                "image": data["playlists"]["items"][0]["images"][0]["url"],
            }
        )
    return response


def get_all_trackids(_id, album=False):
    offset = 0
    limit = 50
    tracks = {}
    if album:
        while True:
            results = sp_public.album_tracks(_id, offset=offset, limit=limit) # sp_public kullanıldı
            for track in results["items"]:
                if not track["id"]:
                    continue
                track["artist"] = ",".join(
                    [artist["name"] for artist in track["artists"]]
                )
                tracks[track["id"]] = {
                    "name": track["name"],
                    "track_number": track["track_number"],
                    "artist": track["artist"],
                    "duration": format_duration(track["duration_ms"]),
                }
            offset += limit
            if len(results["items"]) < limit:
                break
    else:
        while True:
            results = sp_public.playlist_tracks(_id, offset=offset, limit=limit) # sp_public kullanıldı
            for track in results["items"]:
                if not track["track"]["id"]:
                    continue
                track["track"]["artist"] = ",".join(
                    [artist["name"] for artist in track["track"]["artists"]]
                )
                tracks[track["track"]["id"]] = {
                    "name": track["track"]["name"],
                    "track_number": track["track"]["track_number"],
                    "artist": track["track"]["artist"],
                    "album": track["track"]["album"]["name"],
                    "duration": format_duration(track["track"]["duration_ms"]),
                }
            offset += limit
            if len(results["items"]) < limit:
                break
    return tracks


def get_lyrics_from_api(track_id: str):
    """
    Verilen Spotify track ID'si için bir dış API'dan şarkı sözlerini alır.
    Şarkı sözlerini düz metin olarak döndürür.
    """
    if not track_id:
        return None

    lyrics_api_url = f"https://spotify-lyrics-api-pi.vercel.app/?trackid={track_id}&format=lrc"
    try:
        response = requests.get(lyrics_api_url, timeout=10) # timeout eklendi
        response.raise_for_status()  # HTTP hataları için exception fırlatır (4xx, 5xx)
        data = response.json()

        if not data or data.get("error") == True or not data.get("lines"):
            return None # Hata varsa veya söz yoksa

        lyrics_lines = []
        # Hem senkronize hem de senkronize olmayan sözleri düz metin olarak alalım
        for line in data.get("lines", []):
            lyrics_lines.append(line.get("words", ""))
        
        return "\n".join(lyrics_lines) if lyrics_lines else None

    except requests.exceptions.RequestException as e:
        print(f"Lyrics API request error for track {track_id}: {e}")
        return None
    except Exception as e:
        print(f"Error processing lyrics for track {track_id}: {e}")
        return None

def get_chatgpt_interpretation(lyrics: str, track_name: str, artist_name: str) -> str:
    print("get_chatgpt_interpretation fonksiyonu çağrıldı.")  # Debug
    api_key = os.getenv("OPENAI_API_KEY")
    
    # API anahtarını kontrol et
    if not api_key:
        print("HATA: OPENAI_API_KEY ortam değişkeni bulunamadı.")
        return "OpenAI API anahtarı bulunamadı."
    else:
        print(f"API anahtarı başarıyla alındı. Uzunluk: {len(api_key)} karakter")
        print(f"API Key (ilk 5): {api_key[:5]}...{api_key[-5:]}")  # İlk ve son 5 karakteri göster
    
    if not lyrics:
        print("UYARI: Yorumlanacak şarkı sözü yok.")
        return "Yorumlamak için şarkı sözü bulunamadı."
    
    try:
        print("OpenAI istemcisi oluşturuluyor...")  # Debug
        # Proxies parametresini kaldırarak OpenAI istemcisini oluştur
        client = OpenAI(api_key=api_key, http_client=None)
        print("OpenAI istemcisi başarıyla oluşturuldu.")  # Debug
    except Exception as e:
        print(f"HATA: OpenAI istemcisi oluşturulurken hata: {str(e)}")
        return f"OpenAI istemcisi başlatılırken hata oluştu: {str(e)}"

    prompt_template = (
        f"Şarkının adı '{track_name}', sanatçısı '{artist_name}'. "
        f"Bu şarkı sözlerini satır satır analiz et, altındaki anlamları ve duyguları bul. "
        f"Yorumunu 200-300 kelime içinde ver."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes song lyrics."},
                {"role": "user", "content": prompt_template}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI API error: {e}")
        return "ChatGPT'den yorum alınırken bir hata oluştu."

def format_duration(duration_ms):
    minutes = duration_ms // 60000
    seconds = (duration_ms % 60000) // 1000
    seconds = (duration_ms % 60000) // 1000
    # hundredths = (duration_ms % 1000) // 10 # İsteğe bağlı olarak eklenebilir
    return f"{minutes:02d}:{seconds:02d}" # Sadece dakika ve saniye
