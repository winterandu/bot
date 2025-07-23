import discord
from discord.ext import commands
from discord import PCMVolumeTransformer
import yt_dlp
from yt_dlp import *
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from gtts import gTTS
from collections import deque
import asyncio
import os
import math
from dotenv import load_dotenv

# Load environment variables từ file .env
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.reactions = True  # Thêm quyền reactions

# Lấy bot prefix từ .env hoặc dùng default
BOT_PREFIX = os.getenv('BOT_PREFIX', '`')
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None)  # Tắt help mặc định

# Lấy Spotify credentials từ environment variables
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

# Khởi tạo Spotify client nếu credentials có sẵn
spotify = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        auth_manager = SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        )
        spotify = spotipy.Spotify(auth_manager=auth_manager)
        print("✅ Spotify client đã được khởi tạo")
    except Exception as e:
        print(f"⚠️ Không thể khởi tạo Spotify client: {e}")
        spotify = None
else:
    print("⚠️ Spotify credentials không được tìm thấy trong .env file")

def test_spotify_connection():
    """Kiểm tra kết nối Spotify API"""
    if not spotify:
        print("❌ Spotify client chưa được khởi tạo")
        return False
        
    try:
        # Thử lấy thông tin một track test
        spotify.track('4iV5W9uYEdYUVa79Axb7Rh')  # Never Gonna Give You Up :)
        print("✅ Spotify API kết nối thành công")
        return True
    except Exception as e:
        print(f"❌ Lỗi kết nối Spotify API: {e}")
        return False

# Cấu hình yt-dlp
YDL_OPTIONS = {
    "format": "bestaudio[ext=mp3]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "extract_flat": False,
    "source_address": "0.0.0.0",
    "default_search": "ytsearch:",  # Tự động tìm kiếm trên YouTube
    "no_warnings": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# Biến toàn cục
queue = deque()
is_playing = False
is_looping = False
current_song = None
current_song_info = None  # Thêm biến để lưu thông tin chi tiết bài hát
force_skip = False
volume_level = 0.5
current_player = None

# Cache để lưu tên bài hát
song_title_cache = {}  # {query: title}

def format_duration(duration: float) -> str:
    """Định dạng thời lượng từ giây sang phút:giây"""
    if duration <= 0:
        return "Live"
    
    minutes = int(duration // 60)
    seconds = int(round(duration % 60))
    return f"{minutes}:{seconds:02d}"

async def get_song_title_from_query(query):
    """Lấy tên bài hát từ query để hiển thị"""
    try:
        # Nếu là URL, thử lấy thông tin
        if "youtube.com" in query or "youtu.be" in query or "soundcloud.com" in query:
            audio_info = await get_audio_info(query)
            if audio_info:
                return audio_info['title']
        
        # Nếu không phải URL, trả về query gốc
        return query
    except:
        return query

async def get_display_title(query, use_cache=True):
    """Lấy tên hiển thị cho bài hát với cache để tăng tốc độ"""
    global song_title_cache
    
    # Kiểm tra cache trước
    if use_cache and query in song_title_cache:
        return song_title_cache[query]
    
    try:
        # Xử lý Spotify URL trước
        processed_query = query
        if "open.spotify.com/track" in query or "spotify:track:" in query:
            spotify_query = await process_spotify_track(query)
            if spotify_query:
                processed_query = spotify_query
        
        # Xử lý SoundCloud URL
        elif "soundcloud.com" in query:
            soundcloud_url = await process_soundcloud_track(query)
            if soundcloud_url:
                processed_query = soundcloud_url
        
        # Nếu là URL, lấy thông tin chi tiết
        if ("youtube.com" in processed_query or "youtu.be" in processed_query or 
            "soundcloud.com" in processed_query):
            audio_info = await get_audio_info(processed_query)
            if audio_info and audio_info.get('title'):
                title = audio_info['title']
                # Lưu vào cache
                song_title_cache[query] = title
                return title
        
        # Fallback về query gốc
        display_title = query[:60] + ('...' if len(query) > 60 else '')
        song_title_cache[query] = display_title
        return display_title
        
    except Exception as e:
        # Nếu có lỗi, sử dụng query gốc
        display_title = query[:60] + ('...' if len(query) > 60 else '')
        song_title_cache[query] = display_title
        return display_title

@bot.event
async def on_ready():
    print(f'✅ Bot đang chạy: {bot.user}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="`help"))

@bot.command()
async def help(ctx):
    """Hiện bảng help"""
    embed = discord.Embed(
        title="📋 Danh sách lệnh bot nhạc",
        description="Dưới đây là tất cả các lệnh có sẵn:",
        color=discord.Color.blue()
    )
    
    commands_list = [
        "**play** - Phát nhạc từ YouTube, SoundCloud hoặc Spotify(Spotify sẽ bị delay)",
        "**loop** - Bật/tắt chế độ lặp lại bài hát hiện tại",
        "**pause** - Tạm dừng phát nhạc",
        "**resume** - Tiếp tục phát nhạc",
        "**skip** - Bỏ qua bài hát hiện tại",
        "**stop** - Dừng phát nhạc và xóa hàng chờ",
        "**now** - Hiển thị bài hát đang phát",
        "**queue** - Hiển thị danh sách hàng chờ - Sử dụng: queue [số_trang]",
        "**queuenext** - Chuyển sang trang tiếp theo của hàng chờ",
        "**queueprev** - Chuyển về trang đầu của hàng chờ",
        "**volume** - Điều chỉnh âm lượng (0.0-2.0)",
        "**leave** - Rời khỏi voice channel",
        "**speak** - Đọc văn bản bằng giọng nói",
    ]
    
    embed.add_field(
        name="Các lệnh chính",
        value="\n".join(commands_list),
        inline=False
    )
    
    # Thêm thông tin về aliases
    embed.add_field(
        name="⚡ Lệnh tắt",
        value="```⏯️ p = play\n⏭️ n = skip\n⏹️ s = stop\n📃 q = queue```",
        inline=True
    )
    
    
    embed.set_footer(
        text=f"Sử dụng {BOT_PREFIX}<lệnh> để thực hiện | Bot được tạo bởi Laam.",
        icon_url=ctx.author.avatar.url if ctx.author.avatar else None
    )
    
    embed.timestamp = ctx.message.created_at
    
    await ctx.send(embed=embed)


@bot.command()
async def leave(ctx):
    """Rời khỏi voice channel"""
    if ctx.voice_client:
        queue.clear()
        await ctx.voice_client.disconnect()
        await ctx.send("✅ Đã rời khỏi voice channel")
    else:
        await ctx.send("❌ Bot không ở trong voice channel")

async def process_spotify_track(url):
    """Xử lý Spotify track"""
    if not spotify:
        print("❌ Spotify client không có sẵn")
        return None
        
    try:
        # Tìm track ID từ nhiều định dạng URL khác nhau
        track_id_patterns = [
            r'track/([a-zA-Z0-9]+)',  # URL thông thường
            r'spotify:track:([a-zA-Z0-9]+)',  # URI format
        ]
        
        track_id = None
        for pattern in track_id_patterns:
            match = re.search(pattern, url)
            if match:
                track_id = match.group(1)
                break
        
        if not track_id:
            print(f"Không tìm thấy track ID trong URL: {url}")
            return None
            
        # Lấy thông tin track từ Spotify API
        track = spotify.track(track_id)
        
        # Tạo query tìm kiếm tối ưu cho YouTube
        artists = [artist['name'] for artist in track['artists']]
        artist_str = ', '.join(artists)
        
        # Thử nhiều format tìm kiếm
        search_queries = [
            f"{track['name']} {artist_str}",
            f"{track['name']} - {artist_str} official audio",
            f"{track['name']} {artist_str} lyrics",
            f"{artist_str} - {track['name']}"
        ]
        
        print(f"Spotify track: {track['name']} by {artist_str}")
        return search_queries[0]  # Sử dụng query đầu tiên
        
    except spotipy.exceptions.SpotifyException as e:
        print(f"Spotify API error: {e}")
        return None
    except Exception as e:
        print(f"Spotify processing error: {e}")
        return None

async def process_soundcloud_track(url):
    """Xử lý SoundCloud track"""
    try:
        clean_url = url.split('?')[0]
        return clean_url
    except:
        return None

async def get_audio_info(query):
    """Lấy thông tin audio từ yt-dlp"""
    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
            
            if not info:
                return None
                
            if 'entries' in info:
                info = info['entries'][0]
                
            return {
                'url': info['url'],
                'title': info.get('title', 'Không rõ tiêu đề'),
                'duration': info.get('duration', 0),
                'webpage_url': info.get('webpage_url', query),
                'thumbnail': info.get('thumbnail', None)
            }
    except Exception as e:
        print(f"Error getting audio info: {e}")
        return None

async def play_next():
    global is_playing, current_song, force_skip, current_player, current_song_info
    
    if not queue:
        is_playing = False
        current_song_info = None
        return
        
    is_playing = True
    ctx, query = queue.popleft()
    current_song = (ctx, query)
    vc = ctx.voice_client
    
    if not vc:
        await ctx.send("❌ Bot không ở trong voice channel")
        is_playing = False
        return
    
    # Hiển thị thông báo "Đang chuẩn bị" ngay lập tức
    preparing_msg = await ctx.send("⏯️ **Đang chuẩn bị phát nhạc...**")
    
    # Xử lý Spotify URL
    if "open.spotify.com/track" in query or "spotify:track:" in query:
        await preparing_msg.edit(content="⏯️ Đang xử lý link Spotify...")
        spotify_query = await process_spotify_track(query)
        if spotify_query:
            query = spotify_query
            await preparing_msg.edit(content=f"✅ Đã tìm thấy bài hát từ Spotify: `{query[:50]}...`")
        else:
            await preparing_msg.edit(content="❌ Không thể xử lý link Spotify này. Vui lòng kiểm tra lại link hoặc thử link khác.")
            return await play_next()
    
    # Xử lý SoundCloud URL
    elif "soundcloud.com" in query:
        await preparing_msg.edit(content="⏯️ Đang xử lý link SoundCloud...")
        soundcloud_url = await process_soundcloud_track(query)
        if soundcloud_url:
            query = soundcloud_url
        else:
            await preparing_msg.edit(content="❌ Không thể xử lý link SoundCloud này")
            return await play_next()
    
    # Cập nhật thông báo đang tải
    await preparing_msg.edit(content="🔄 **Đang tải nhạc...**")
    
    # Lấy thông tin audio
    audio_info = await get_audio_info(query)
    if not audio_info:
        await preparing_msg.edit(content=f"❌ Không tìm thấy bài hát: `{query}`")
        return await play_next()
    
    # Lưu thông tin chi tiết bài hát hiện tại
    current_song_info = audio_info
    
    # Tạo audio source
    try:
        audio_source = discord.FFmpegPCMAudio(
            audio_info['url'],
            **FFMPEG_OPTIONS
        )
    except Exception as e:
        await preparing_msg.edit(content=f"❌ Lỗi khi tạo nguồn âm thanh: {e}")
        return await play_next()
    
    def after_playing(error):
        if error:
            print(f"Playback error: {error}")
        
        coro = replay_current() if is_looping else play_next()
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            future.result()
        except Exception as e:
            print(f"Error in after_playing: {e}")
    
    try:
        current_player = PCMVolumeTransformer(audio_source, volume=volume_level)
        vc.play(current_player, after=after_playing)
        
        # Hiển thị thông tin bài hát ngay khi bắt đầu phát
        duration_str = format_duration(audio_info['duration'])
        
        embed = discord.Embed(
            title="🎶 Đang phát",
            description=f"[{audio_info['title']}]({audio_info['webpage_url']})",
            color=discord.Color.blue()
        )
        embed.add_field(name="⏳ Thời lượng", value=duration_str)
        embed.set_footer(text=f"Yêu cầu bởi {ctx.author.display_name}", icon_url=ctx.author.avatar.url)
        
        # Cập nhật thông báo chuẩn bị thành thông báo đang phát
        await preparing_msg.edit(content="", embed=embed)
        
    except Exception as e:
        await preparing_msg.edit(content=f"❌ Lỗi khi phát nhạc: {e}")
        return await play_next()

async def replay_current():
    global current_song
    if current_song:
        queue.appendleft(current_song)
        await play_next()

async def show_added_track(ctx, query):
    """Hiển thị thông báo bài hát đã được thêm vào hàng chờ với tên bài hát thực"""
    # Tính toán vị trí trong hàng chờ
    queue_position = len(queue)
    
    # Lấy tên bài hát thực tế và lưu vào cache
    try:
        song_title = await get_display_title(query, use_cache=True)
    except Exception as e:
        # Nếu có lỗi, sử dụng query gốc
        song_title = query[:60] + ('...' if len(query) > 60 else '')
    
    embed = discord.Embed(
        title="✅ Đã thêm vào hàng chờ",
        description=f"⏯️ `{song_title}`",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="📍 Vị trí", 
        value=f"#{queue_position}", 
        inline=True
    )
    

    
    embed.set_footer(
        text=f"Yêu cầu bởi {ctx.author.display_name}", 
        icon_url=ctx.author.avatar.url if ctx.author.avatar else None
    )
    
    await ctx.send(embed=embed)
    

@bot.command(aliases=['p'])
async def play(ctx, *, query):
    """Phát nhạc từ YouTube, SoundCloud hoặc Spotify"""
    if not ctx.author.voice:
        return await ctx.send("❌ Bạn cần vào voice channel trước.")
    
    vc = ctx.voice_client
    if not vc:
        vc = await ctx.author.voice.channel.connect()
    
    # Thêm vào hàng chờ
    queue.append((ctx, query))
    
    # Chỉ hiển thị thông báo "đã thêm vào hàng chờ" nếu đang có bài khác phát
    if is_playing:
        await show_added_track(ctx, query)
    
    # Chạy play_next() trong background nếu không có bài nào đang phát
    if not is_playing:
        # Tạo task để chạy song song, không chờ đợi
        asyncio.create_task(play_next())

@bot.command()
async def pause(ctx):
    """Tạm dừng phát nhạc"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Đã tạm dừng.")
    else:
        await ctx.send("❌ Không có bài hát nào đang phát.")

@bot.command()
async def resume(ctx):
    """Tiếp tục phát nhạc"""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Đã tiếp tục.")
    else:
        await ctx.send("❌ Không có bài hát nào bị tạm dừng.")

@bot.command(aliases=['s'])
async def stop(ctx):
    """Dừng phát nhạc và xóa hàng chờ"""
    global queue, is_playing, is_looping, force_skip, current_song, current_song_info
    if ctx.voice_client:
        is_playing = False
        is_looping = False
        force_skip = False
        queue.clear()
        current_song = None
        current_song_info = None
        ctx.voice_client.stop()
        await ctx.send("⏹️ Đã dừng phát và xóa hàng chờ.")
    else:
        await ctx.send("❌ Bot không ở trong voice channel.")

@bot.command(aliases=['next', 'n'])
async def skip(ctx):
    """Bỏ qua bài hát hiện tại"""
    global force_skip
    if ctx.voice_client and ctx.voice_client.is_playing():
        force_skip = True
        ctx.voice_client.stop()
        await ctx.send("⏭️ Đã bỏ qua bài hát.")
        await asyncio.sleep(1)
        force_skip = False
    else:
        await ctx.send("❌ Không có bài hát nào đang phát.")

@bot.command()
async def loop(ctx):
    """Bật/tắt chế độ lặp lại bài hát hiện tại"""
    global is_looping
    is_looping = not is_looping
    await ctx.send(f"🔁 Chế độ lặp {'đã bật' if is_looping else 'đã tắt'}.")

@bot.command(name='queue', aliases=['list', 'q'])
async def show_queue(ctx, page: int = 1):
    """Hiển thị danh sách hàng chờ - Sử dụng: queue [số_trang]"""
    if not queue:
        embed = discord.Embed(
            title="📃 Hàng chờ",
            description="❌ Hàng chờ trống.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Yêu cầu bởi {ctx.author.display_name}", icon_url=ctx.author.avatar.url)
        return await ctx.send(embed=embed)
    
    # Tính toán phân trang
    songs_per_page = 10
    total_pages = math.ceil(len(queue) / songs_per_page)
    
    # Kiểm tra số trang hợp lệ
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    
    start_index = (page - 1) * songs_per_page
    end_index = min(start_index + songs_per_page, len(queue))
    
    embed = discord.Embed(
        title="📃 Hàng chờ nhạc",
        color=discord.Color.blue()
    )
    
    # Tạo danh sách các bài hát trong hàng chờ
    queue_list = []
    queue_items = [item for item in queue]  # Convert deque to list
    
    # Strategy mới: Chỉ lấy title chi tiết cho 3 bài đầu, còn lại dùng query hoặc cache
    priority_songs = []  # Các bài ưu tiên (3 bài đầu)
    regular_songs = []   # Các bài còn lại
    
    for i in range(start_index, end_index):
        _, query = queue_items[i]
        
        if i < 3:  # 3 bài đầu tiên - lấy title chi tiết
            priority_songs.append((i, query))
        else:  # Các bài còn lại - dùng cache hoặc query gốc
            regular_songs.append((i, query))
    
    # Lấy title cho các bài ưu tiên song song (async)
    priority_titles = {}
    if priority_songs:
        priority_tasks = []
        for i, query in priority_songs:
            task = get_display_title(query, use_cache=True)
            priority_tasks.append((i, task))
        
        # Chạy song song để giảm delay
        for i, task in priority_tasks:
            try:
                title = await asyncio.wait_for(task, timeout=2.0)  # Timeout 2s mỗi bài
                priority_titles[i] = title
            except asyncio.TimeoutError:
                # Nếu timeout, dùng cache hoặc query gốc
                _, query = queue_items[i]
                priority_titles[i] = song_title_cache.get(query, query[:45] + ('...' if len(query) > 45 else ''))
            except:
                _, query = queue_items[i]
                priority_titles[i] = query[:45] + ('...' if len(query) > 45 else '')
    
    # Tạo danh sách hiển thị
    for i in range(start_index, end_index):
        _, query = queue_items[i]
        
        if i in priority_titles:
            display_title = priority_titles[i]
        else:
            # Dùng cache hoặc query gốc cho các bài không ưu tiên
            if query in song_title_cache:
                display_title = song_title_cache[query]
            else:
                display_title = query
        
        # Cắt tên bài hát nếu quá dài
        if len(display_title) > 45:
            display_title = display_title[:45] + "..."
        
        # Thêm icon khác nhau cho vị trí
        if i == 0:
            icon = "🥇"  # Bài tiếp theo
        elif i == 1:
            icon = "🥈"
        elif i == 2:
            icon = "🥉"
        else:
            icon = f"{i + 1}️⃣" if i < 9 else f"`{i + 1}`"
        
        queue_list.append(f"{icon} {display_title}")
    
    if queue_list:
        embed.add_field(
            name=f"📋 Danh sách ({len(queue)} bài)",
            value="\n".join(queue_list),
            inline=False
        )
    
    # Thêm thông tin thống kê
    embed.add_field(
        name="📊 Thống kê",
        value=f"```📝 Tổng: {len(queue)} bài\n📄 Trang: {page}/{total_pages}\n🔁 Lặp: {'Bật' if is_looping else 'Tắt'}\n🔊 Âm lượng: {int(volume_level * 100)}%```",
        inline=True
    )
    
    # Thêm hướng dẫn
    embed.add_field(
        name="💡 Lệnh hữu ích",
        value="```⏯️ `play/p <tên bài> - Thêm bài\n⏭️ `skip/next/n - Bỏ qua\n⏸️ `pause - Tạm dừng\n🔁 `loop - Bật/tắt lặp\n⏹️ `stop/s - Dừng hết```",
        inline=True
    )
    
    embed.set_footer(
        text=f"Yêu cầu bởi {ctx.author.display_name} • Trang {page}/{total_pages}",
        icon_url=ctx.author.avatar.url
    )
    
    # Thêm timestamp
    embed.timestamp = ctx.message.created_at
    
    message = await ctx.send(embed=embed)
    
    # Thêm reaction để chuyển trang nếu có nhiều trang
    if total_pages > 1:
        reactions = []
        if page > 1:
            reactions.append("⬅️")  # Trang trước
        if page < total_pages:
            reactions.append("➡️")  # Trang sau
        reactions.extend(["🔄"])  # Refresh và Close
        
        try:
            for reaction in reactions:
                await message.add_reaction(reaction)
        except Exception as e:
            print(f"Error adding reactions: {e}")
        
        # Tạo listener cho reaction
        def check(reaction, user):
            return (user == ctx.author and 
                   str(reaction.emoji) in ["⬅️", "➡️", "🔄"] and 
                   reaction.message.id == message.id)
        
        try:
            while True:
                reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
                
                if str(reaction.emoji) == "⬅️" and page > 1:
                    # Chuyển trang trước
                    new_page = page - 1
                    await message.delete()
                    await show_queue(ctx, new_page)
                    break
                    
                elif str(reaction.emoji) == "➡️" and page < total_pages:
                    # Chuyển trang sau
                    new_page = page + 1
                    await message.delete()
                    await show_queue(ctx, new_page)
                    break
                    
                elif str(reaction.emoji) == "🔄":
                    # Refresh trang hiện tại
                    await message.delete()
                    await show_queue(ctx, page)
                    break
                    

                
                # Xóa reaction của user để họ có thể click lại
                await message.remove_reaction(reaction.emoji, user)
                
        except asyncio.TimeoutError:
            # Xóa tất cả reaction sau 60 giây
            try:
                await message.clear_reactions()
            except:
                pass

@bot.command(name='queuenext', aliases=['qn'])
async def queue_next_page(ctx):
    """Chuyển sang trang tiếp theo của hàng chờ"""
    if not queue:
        return await ctx.send("❌ Hàng chờ trống.")
    
    songs_per_page = 10
    total_pages = math.ceil(len(queue) / songs_per_page)
    
    # Mặc định chuyển sang trang 2
    await show_queue(ctx, 2)

@bot.command(name='queueprev', aliases=['qp'])
async def queue_prev_page(ctx):
    """Chuyển về trang đầu của hàng chờ"""
    if not queue:
        return await ctx.send("❌ Hàng chờ trống.")
    
    # Chuyển về trang 1
    await show_queue(ctx, 1)

@bot.command()
async def volume(ctx, level: float = None):
    """Điều chỉnh âm lượng (0.0-2.0)"""
    global volume_level, current_player
    
    if level is None:
        return await ctx.send(f"🔊 Âm lượng hiện tại: {int(volume_level * 100)}%")
    
    if 0.0 <= level <= 2.0:
        volume_level = level
        if current_player:
            current_player.volume = volume_level
        await ctx.send(f"🔊 Đã đặt âm lượng: {int(volume_level * 100)}%")
    else:
        await ctx.send("❌ Âm lượng phải từ 0.0 đến 2.0 (0% đến 200%)")

@bot.command()
async def now(ctx):
    """Hiển thị bài hát đang phát"""
    if current_song and current_song_info:
        title = current_song_info['title']
        duration_str = format_duration(current_song_info['duration'])
        webpage_url = current_song_info['webpage_url']
        
        embed = discord.Embed(
            title="🎶 Đang phát",
            description=f"[{title}]({webpage_url})",
            color=discord.Color.blue()
        )
        embed.add_field(name="⏳ Thời lượng", value=duration_str, inline=True)
        embed.add_field(name="🔊 Âm lượng", value=f"{int(volume_level * 100)}%", inline=True)
        embed.add_field(name="🔁 Lặp", value="Bật" if is_looping else "Tắt", inline=True)
        
        # Thêm footer với người yêu cầu
        if current_song:
            requester_ctx, _ = current_song
            embed.set_footer(text=f"Yêu cầu bởi {requester_ctx.author.display_name}", icon_url=requester_ctx.author.avatar.url)
        
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Không có bài hát nào đang phát.")

@bot.command()
async def clearcache(ctx):
    """Xóa cache tên bài hát để làm mới"""
    global song_title_cache
    song_title_cache.clear()
    await ctx.send("🗑️ Đã xóa cache tên bài hát.")

@bot.command()
async def speak(ctx, *, message: str):
    """Đọc văn bản bằng giọng nói"""
    if not ctx.author.voice:
        return await ctx.send("❌ Bạn cần vào voice channel trước.")
    
    vc = ctx.voice_client
    if not vc:
        vc = await ctx.author.voice.channel.connect()
    
    tts = gTTS(text=message, lang='vi')
    tts.save("tts.mp3")
    
    if vc.is_playing():
        vc.stop()
    
    vc.play(discord.FFmpegPCMAudio("tts.mp3"))
    await ctx.send(f"🗣️ Đang đọc: `{message}`")
    
    await asyncio.sleep(1)
    if os.path.exists("tts.mp3"):
        os.remove("tts.mp3")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "hiếu" in message.content.lower():
        await message.channel.send("Em cảm ơn anh Hiếu nhiều nháa")
        
    if "cáo" in message.content.lower():
        await message.channel.send("Em cảm ơn anh Cáo đã giúp em ạa")
        
    

    await bot.process_commands(message)

  

# Lấy Discord token từ environment variable
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN không được tìm thấy trong .env file!")
    print("Vui lòng thêm DISCORD_TOKEN vào file .env")
    exit(1)

# Chạy bot
try:
    bot.run(DISCORD_TOKEN)
except discord.LoginFailure:
    print("❌ Discord token không hợp lệ!")
except Exception as e:
    print(f"❌ Lỗi khi chạy bot: {e}")