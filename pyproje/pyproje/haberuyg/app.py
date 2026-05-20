from flask import Flask, render_template, request, redirect, jsonify, session, flash
from flask import send_from_directory
import sqlite3
import requests
from urllib.parse import urlencode


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "1234"

app = Flask(__name__)
app.secret_key = "gizli_anahtar"

API_KEY = "9598db7c2226420a9ce2e94b38145c1e"


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "favicon.jpg", mimetype="image/jpeg")


def get_db_connection():
    conn = sqlite3.connect("news.db")
    conn.row_factory = sqlite3.Row
    return conn


def create_tables():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            url TEXT NOT NULL,
            image_url TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT,
            read_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            url TEXT,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            UNIQUE(user_id, url)
       )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


import feedparser

def get_news(category="", search=""):
    import re 
    if not category and not search:
        rss_url = "https://www.trthaber.com/manset_articles.rss"
        try:
            feed = feedparser.parse(rss_url)
            articles = []
            for entry in feed.entries:
                raw_description = entry.get('summary', '')
                clean_description = re.sub(r'<[^>]+>', '', raw_description).strip()

                articles.append({
                    'title': entry.title,
                    'description': clean_description,
                    'url': entry.link,
                    "source": entry.link.split("/")[2].replace("www.","").split(".")[0].capitalize(),
                    'urlToImage': entry.get('links', [{}])[0].get('href', 'https://via.placeholder.com/800x450?text=Haber') 
                })
            return articles[:20]
        except:
            return []
            
    else:
        if search:
            url = f"https://newsapi.org/v2/everything?q={search}&language=tr&apiKey={API_KEY}"
        elif category:
            url = f"https://newsapi.org/v2/everything?q={category}&language=tr&sortBy=publishedAt&apiKey={API_KEY}"
            
        try:
            response = requests.get(url, timeout=3)
            data = response.json()
            return data.get("articles", [])[:20]
        except:
            return []


@app.route("/")
def index():
    category = request.args.get("category", "")
    search = request.args.get("search", "")
    view = request.args.get("view", "grid")

    articles = get_news(category, search)
    
    # -------------------------------------------------------------------
    # DÜZELTME: Eski (hatalı) string çerezleri otomatik temizleme sistemi
    raw_hidden = session.get("hidden_articles", [])
    hidden_articles = []
    hidden_urls = []
    
    for art in raw_hidden:
        if isinstance(art, dict): # Sadece yeni formattaki sözlükleri kabul et
            hidden_articles.append(art)
            hidden_urls.append(art.get("url"))
            
    # Eğer hatalı veri bulunmuş ve silinmişse session'ı güncelle
    if len(raw_hidden) != len(hidden_articles):
        session["hidden_articles"] = hidden_articles
        session.modified = True
    # -------------------------------------------------------------------

    articles = [
        article for article in articles
        if article.get("url") not in hidden_urls
    ]

    favorite_map = {}
    if "user_id" in session:
        conn = get_db_connection()
        favorite_map = {
            row["url"]: row["id"] for row in conn.execute(
                "SELECT id, url FROM favorites WHERE user_id = ?",
                (session["user_id"],)
            ).fetchall()
        }
        
    conn = get_db_connection()
    likes_data = conn.execute("""
        SELECT url, SUM(likes) as total_likes, SUM(dislikes) as total_dislikes 
        FROM article_likes GROUP BY url
    """).fetchall()
    
    user_votes = {}
    if "user_id" in session:
        user_id = session["user_id"]
        user_data = conn.execute("SELECT url, likes, dislikes FROM article_likes WHERE user_id = ?", (user_id,)).fetchall()
        user_votes = {row["url"]: {"liked": row["likes"], "disliked": row["dislikes"]} for row in user_data}
        
    comments_data = conn.execute("SELECT url, username, text, created_at FROM comments ORDER BY id DESC").fetchall()
    conn.close()
    
    likes_map = {}
    if "user_id" in session:
        for row in likes_data:
            url = row["url"]
            is_user_liked = user_votes.get(url, {}).get("liked", 0) if user_votes else 0
            is_user_disliked = user_votes.get(url, {}).get("disliked", 0) if user_votes else 0
            
            likes_map[url] = {
                "likes": row["total_likes"], 
                "dislikes": row["total_dislikes"],
                "user_liked": is_user_liked,
                "user_disliked": is_user_disliked
            }
    else:
        for row in likes_data:
            likes_map[row["url"]] = {
                "likes": 0, "dislikes": 0, "user_liked": 0, "user_disliked": 0
            }

    comments_map = {}
    for row in comments_data:
        if row["url"] not in comments_map:
            comments_map[row["url"]] = []
        comments_map[row["url"]].append({
            "username": row["username"],
            "text": row["text"],
            "created_at": row["created_at"][:16]
        })

    return render_template(
        "index.html",
        articles=articles,
        category=category,
        search=search,
        view=view,
        hidden_count=len(hidden_articles),
        favorite_map=favorite_map,
        likes_map=likes_map
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        if username == "" or password == "":
            flash("Kullanıcı adı ve şifre boş bırakılamaz.")
            return redirect("/register")

        username_control = get_db_connection()

        existing_user = username_control.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        username_control.close()

        if existing_user:
            flash("Bu kullanıcı adı zaten kullanılıyor.")
            return redirect("/register")

        try:
            conn = get_db_connection()

            cursor = conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )

            conn.commit()

            session["user_id"] = cursor.lastrowid
            session["username"] = username

            conn.close()

            flash("Kayıt başarılı. Ana sayfaya yönlendirildiniz.")
            return redirect("/")

        except:
            flash("Bu kullanıcı adı zaten kullanılıyor.")
            return redirect("/register")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Giriş başarılı.")
            return redirect("/")
        else:
            flash("Kullanıcı adı veya şifre hatalı.")
            return redirect("/login")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Çıkış yapıldı.")
    return redirect("/")


@app.route("/remove_favorite_home", methods=["POST"])
def remove_favorite_home():
    if "user_id" not in session:
        flash("Bu işlem için giriş yapmalısınız.")
        return redirect("/login")

    favorite_id = request.form.get("favorite_id", "").strip()
    category = request.form.get("category", "").strip()
    search = request.form.get("search", "").strip()
    view = request.form.get("view", "").strip()

    if favorite_id:
        conn = get_db_connection()
        conn.execute(
            "DELETE FROM favorites WHERE id = ? AND user_id = ?",
            (favorite_id, session["user_id"])
        )
        conn.commit()
        conn.close()
        flash("Haber favorilerden çıkarıldı.")

    query_parts = {}

    if category:
        query_parts["category"] = category

    if search:
        query_parts["search"] = search

    if view and view != "grid":
        query_parts["view"] = view

    redirect_url = "/"

    if query_parts:
        redirect_url += "?" + urlencode(query_parts)

    return redirect(redirect_url)


@app.route("/add_favorite", methods=["POST"])
def add_favorite():
    if "user_id" not in session:
        return jsonify({"success": False})

    title = request.form.get("title")
    description = request.form.get("description")
    image_url = request.form.get("image_url")
    url = request.form.get("url")

    conn = get_db_connection()

    existing = conn.execute(
        "SELECT * FROM favorites WHERE user_id = ? AND url = ?",
        (session["user_id"], url)
    ).fetchone()

    # Favoriden kaldır
    if existing:
        conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND url = ?",
            (session["user_id"], url)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "favorited": False})
    # Favoriye ekle
    else:
        conn.execute("""
            INSERT INTO favorites (user_id, title, description, image_url, url)
            VALUES (?, ?, ?, ?, ?)
        """, (session["user_id"], title, description, image_url, url))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "favorited": True})


@app.route("/read")
def read_news():
    title = request.args.get("title", "").strip()
    url = request.args.get("url", "").strip()
    source = request.args.get("source", "").strip()

    if not url:
        flash("Haber bağlantısı bulunamadı.")
        return redirect("/")

    if "user_id" in session:
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO reads (user_id, title, url, source)
            VALUES (?, ?, ?, ?)
        """, (
            session["user_id"],
            title if title else "Başlıksız Haber",
            url,
            source if source else "Kaynak yok"
        ))
        conn.commit()
        conn.close()

    return redirect(url)


@app.route("/delete_read/<int:id>")
def delete_read(id):
    if "user_id" not in session:
        flash("Bu işlem için giriş yapmalısınız.")
        return redirect("/login")

    conn = get_db_connection()
    conn.execute(
        "DELETE FROM reads WHERE id = ? AND user_id = ?",
        (id, session["user_id"])
    )
    conn.commit()
    conn.close()

    flash("Okuma kaydı silindi.")
    return redirect("/profile")


@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            flash("Yönetici girişi başarılı.")
            return redirect("/admin_panel")

        flash("Yönetici bilgileri hatalı.")
        return redirect("/admin_login")

    session.pop("admin", None)
    return render_template("admin_login.html")


@app.route("/admin_panel")
def admin_panel():
    if session.get("admin") != True:
        flash("Önce yönetici girişi yapmalısınız.")
        return redirect("/admin_login")

    conn = get_db_connection()

    user_search = request.args.get("user_search", "").strip()
    news_search = request.args.get("news_search", "").strip()

    all_users = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()

    if user_search:
        users = conn.execute(
            "SELECT * FROM users WHERE username LIKE ? ORDER BY id DESC",
            (f"%{user_search}%",)
        ).fetchall()
    else:
        users = all_users

    all_favorites = conn.execute("""
        SELECT favorites.*, users.username
        FROM favorites
        LEFT JOIN users ON favorites.user_id = users.id
        ORDER BY favorites.id DESC
    """).fetchall()

    if news_search:
        favorites = conn.execute("""
            SELECT favorites.*, users.username
            FROM favorites
            LEFT JOIN users ON favorites.user_id = users.id
            WHERE favorites.title LIKE ? OR users.username LIKE ?
            ORDER BY favorites.id DESC
        """, (f"%{news_search}%", f"%{news_search}%")).fetchall()
    else:
        favorites = all_favorites

    recent_users = all_users[:5]
    recent_favorites = all_favorites[:5]
    user_count = len(all_users)
    favorite_count = len(all_favorites)

    read_count = conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0]
    today_read_count = conn.execute(
        "SELECT COUNT(*) FROM reads WHERE DATE(read_at) = DATE('now')"
    ).fetchone()[0]

    top_reads = conn.execute("""
        SELECT title, url, source, COUNT(*) AS read_total
        FROM reads
        GROUP BY url
        ORDER BY read_total DESC, MAX(id) DESC
        LIMIT 5
    """).fetchall()

    active_readers = conn.execute("""
        SELECT users.id, users.username, COUNT(reads.id) AS read_total
        FROM reads
        INNER JOIN users ON reads.user_id = users.id
        GROUP BY reads.user_id
        ORDER BY read_total DESC, users.id DESC
        LIMIT 5
    """).fetchall()

    conn.close()

    return render_template(
        "admin_panel.html",
        users=users,
        favorites=favorites,
        user_count=user_count,
        favorite_count=favorite_count,
        user_search=user_search,
        news_search=news_search,
        recent_users=recent_users,
        recent_favorites=recent_favorites,
        read_count=read_count,
        today_read_count=today_read_count,
        top_reads=top_reads,
        active_readers=active_readers
    )


@app.route("/admin_delete_user/<int:id>")
def admin_delete_user(id):
    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db_connection()

    conn.execute("DELETE FROM favorites WHERE user_id = ?", (id,))
    conn.execute("DELETE FROM reads WHERE user_id = ?", (id,))
    conn.execute("DELETE FROM users WHERE id = ?", (id,))

    conn.commit()
    conn.close()

    flash("Kullanıcı ve kullanıcıya ait favoriler silindi.")
    return redirect("/admin_panel")


@app.route("/admin_edit_user/<int:id>", methods=["GET", "POST"])
def admin_edit_user(id):
    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (id,)
    ).fetchone()

    if user is None:
        conn.close()
        flash("Kullanıcı bulunamadı.")
        return redirect("/admin_panel?tab=users")

    if request.method == "POST":
        new_username = request.form["username"].strip()

        if new_username == "":
            conn.close()
            flash("Kullanıcı adı boş bırakılamaz.")
            return redirect(f"/admin_edit_user/{id}")

        same_username = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (new_username, id)
        ).fetchone()

        if same_username:
            conn.close()
            flash("Bu kullanıcı adı zaten kullanılıyor.")
            return redirect(f"/admin_edit_user/{id}")

        conn.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (new_username, id)
        )

        conn.commit()
        conn.close()

        flash("Kullanıcı adı güncellendi.")
        return redirect("/admin_panel?tab=users")

    conn.close()
    return render_template("edit_user.html", user=user)


@app.route("/admin_user_detail/<int:id>")
def admin_user_detail(id):
    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (id,)
    ).fetchone()

    if user is None:
        conn.close()
        flash("Kullanıcı bulunamadı.")
        return redirect("/admin_panel?tab=users")

    favorites = conn.execute(
        "SELECT * FROM favorites WHERE user_id = ? ORDER BY id DESC",
        (id,)
    ).fetchall()

    favorite_count = len(favorites)

    reads = conn.execute(
        "SELECT * FROM reads WHERE user_id = ? ORDER BY id DESC LIMIT 10",
        (id,)
    ).fetchall()

    read_count = conn.execute(
        "SELECT COUNT(*) FROM reads WHERE user_id = ?",
        (id,)
    ).fetchone()[0]

    user_top_sources = conn.execute("""
        SELECT source, COUNT(*) AS read_total
        FROM reads
        WHERE user_id = ?
        GROUP BY source
        ORDER BY read_total DESC, source ASC
        LIMIT 5
    """, (id,)).fetchall()

    conn.close()

    return render_template(
        "admin_user_detail.html",
        user=user,
        favorites=favorites,
        favorite_count=favorite_count,
        reads=reads,
        read_count=read_count,
        user_top_sources=user_top_sources
    )


@app.route("/admin_delete_favorite/<int:id>")
def admin_delete_favorite(id):
    if not session.get("admin"):
        return redirect("/admin_login")

    conn = get_db_connection()
    conn.execute("DELETE FROM favorites WHERE id = ?", (id,))
    conn.commit()
    conn.close()

    flash("Favori haber silindi.")
    return redirect("/admin_panel")


@app.route("/admin_logout")
def admin_logout():
    session.pop("admin", None)
    flash("Yönetici çıkışı yapıldı.")
    return redirect("/")


@app.route("/profile")
def profile():
    if "user_id" not in session:
        flash("Profili görüntülemek için giriş yapmalısınız.")
        return redirect("/login")

    conn = get_db_connection()
    read_search = request.args.get("read_search", "").strip()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    favorites = conn.execute(
        "SELECT * FROM favorites WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],)
    ).fetchall()

    favorite_count = len(favorites)

    if read_search:
        reads = conn.execute("""
            SELECT * FROM reads
            WHERE user_id = ? AND (title LIKE ? OR source LIKE ?)
            ORDER BY id DESC
            LIMIT 10
        """, (
            session["user_id"],
            f"%{read_search}%",
            f"%{read_search}%"
        )).fetchall()
    else:
        reads = conn.execute(
            "SELECT * FROM reads WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (session["user_id"],)
        ).fetchall()

    read_count = conn.execute(
        "SELECT COUNT(*) FROM reads WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0]

    source_count = conn.execute(
        "SELECT COUNT(DISTINCT source) FROM reads WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0]

    last_read = conn.execute(
        "SELECT * FROM reads WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (session["user_id"],)
    ).fetchone()

    top_user_sources = conn.execute("""
        SELECT source, COUNT(*) AS read_total
        FROM reads
        WHERE user_id = ?
        GROUP BY source
        ORDER BY read_total DESC, source ASC
        LIMIT 5
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template(
        "profile.html",
        user=user,
        favorites=favorites,
        favorite_count=favorite_count,
        reads=reads,
        read_count=read_count,
        read_search=read_search,
        source_count=source_count,
        last_read=last_read,
        top_user_sources=top_user_sources
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        flash("Ayarları görüntülemek için giriş yapmalısınız.")
        return redirect("/login")

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    favorite_count = conn.execute(
        "SELECT COUNT(*) FROM favorites WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0]

    if request.method == "POST":
        new_username = request.form["username"].strip()
        current_password = request.form["current_password"].strip()
        new_password = request.form["password"].strip()
        
        if current_password != user["password"]:
            flash("Mevcut şifre hatalı.")
            conn.close()
            return redirect("/settings")
        
        if new_username == "" or new_password == "":
            flash("Kullanıcı adı ve şifre boş bırakılamaz.")
            conn.close()
            return redirect("/settings")

        same_username = conn.execute(
            "SELECT * FROM users WHERE username = ? AND id != ?",
            (new_username, session["user_id"])
        ).fetchone()

        if same_username:
            flash("Bu kullanıcı adı zaten kullanılıyor.")
            conn.close()
            return redirect("/settings")

        conn.execute(
            "UPDATE users SET username = ?, password = ? WHERE id = ?",
            (new_username, new_password, session["user_id"])
        )

        conn.commit()
        conn.close()

        session["username"] = new_username
        flash("Hesap bilgileri güncellendi.")
        return redirect("/settings")

    conn.close()
    return render_template("settings.html", user=user, favorite_count=favorite_count)


@app.route("/like", methods=["POST"])
def like_article():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Giriş yapmalısınız."})

    url = request.form.get("url")
    user_id = session["user_id"]

    conn = get_db_connection()
    existing = conn.execute(
        "SELECT likes, dislikes FROM article_likes WHERE user_id = ? AND url = ?",
        (user_id, url)
    ).fetchone()

    if existing:
        if existing["likes"] == 1:
            conn.execute("DELETE FROM article_likes WHERE user_id = ? AND url = ?", (user_id, url))
            user_liked, user_disliked = 0, 0
        elif existing["dislikes"] == 1:
            conn.execute(
                "UPDATE article_likes SET likes = 1, dislikes = 0 WHERE user_id = ? AND url = ?",
                (user_id, url)
            )
            user_liked, user_disliked = 1, 0
    else:
        conn.execute(
            "INSERT INTO article_likes (user_id, url, likes, dislikes) VALUES (?, ?, 1, 0)",
            (user_id, url)
        )
        user_liked, user_disliked = 1, 0

    conn.commit()

    totals = conn.execute(
        "SELECT SUM(likes) as total_likes, SUM(dislikes) as total_dislikes FROM article_likes WHERE url = ?",
        (url,)
    ).fetchone()
    
    guncel_like = totals["total_likes"] if totals["total_likes"] is not None else 0
    guncel_dislike = totals["total_dislikes"] if totals["total_dislikes"] is not None else 0
    
    conn.close()

    return jsonify({
        "success": True,
        "likes": guncel_like,
        "dislikes": guncel_dislike,
        "user_liked": user_liked,
        "user_disliked": user_disliked
    })


@app.route("/dislike", methods=["POST"])
def dislike_article():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Giriş yapmalısınız."})

    url = request.form.get("url")
    user_id = session["user_id"]

    conn = get_db_connection()
    existing = conn.execute(
        "SELECT likes, dislikes FROM article_likes WHERE user_id = ? AND url = ?",
        (user_id, url)
    ).fetchone()

    if existing:
        if existing["dislikes"] == 1:
            conn.execute("DELETE FROM article_likes WHERE user_id = ? AND url = ?", (user_id, url))
            user_liked, user_disliked = 0, 0
        elif existing["likes"] == 1:
            conn.execute(
                "UPDATE article_likes SET likes = 0, dislikes = 1 WHERE user_id = ? AND url = ?",
                (user_id, url)
            )
            user_liked, user_disliked = 0, 1
    else:
        conn.execute(
            "INSERT INTO article_likes (user_id, url, likes, dislikes) VALUES (?, ?, 0, 1)",
            (user_id, url)
        )
        user_liked, user_disliked = 0, 1

    conn.commit()

    totals = conn.execute(
        "SELECT SUM(likes) as total_likes, SUM(dislikes) as total_dislikes FROM article_likes WHERE url = ?",
        (url,)
    ).fetchone()
    
    guncel_like = totals["total_likes"] if totals["total_likes"] is not None else 0
    guncel_dislike = totals["total_dislikes"] if totals["total_dislikes"] is not None else 0
    
    conn.close()

    return jsonify({
        "success": True,
        "likes": guncel_like,
        "dislikes": guncel_dislike,
        "user_liked": user_liked,
        "user_disliked": user_disliked
    })


@app.route("/add_comment", methods=["POST"])
def add_comment():
    url = request.form.get("url")
    text = request.form.get("text")

    username = session.get("username",  "Ziyaretçi")

    if not url or not text:
        return redirect(request.referrer or "/")
    
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO comments (url, username,text) VALUES (?, ?, ?)",
        (url, username, text)
    )
    conn.commit()
    conn.close()
    return redirect(request.referrer or "/")


@app.route("/haber_detay")
def haber_detay():
    article = {
        "title": request.args.get("title"),
        "description": request.args.get("description"),
        "urlToImage": request.args.get("image"),
        "url": request.args.get("url")
    }

    conn = get_db_connection()

    comments = conn.execute(
        "SELECT username, text, created_at FROM comments WHERE url = ? ORDER BY id DESC",
        (article["url"],)
    ).fetchall()

    conn.close()

    return render_template(
        "detay.html",
        article=article,
        comments=comments
    )

# -------------------------------------------------------------------
# DÜZELTME: Eski (hatalı) string çerezleri temizlemek için güncellendi
@app.route("/hide_article", methods=["POST"])
def hide_article():
    url = request.form.get("url")
    title = request.form.get("title")
    description = request.form.get("description")
    image = request.form.get("image")

    if url:
        raw_hidden = session.get("hidden_articles", [])
        
        # Sadece dict (sözlük) formatındaki geçerli verileri al
        valid_hidden = [art for art in raw_hidden if isinstance(art, dict)]
        
        # Daha önce gizlenmediyse ekle
        if not any(art.get("url") == url for art in valid_hidden):
            valid_hidden.append({
                "url": url,
                "title": title,
                "description": description,
                "image": image
            })
            session["hidden_articles"] = valid_hidden
            session.modified = True
            
    return redirect(request.referrer or "/")

@app.route("/unhide_article", methods=["POST"])
def unhide_article():
    url = request.form.get("url")
    if url:
        raw_hidden = session.get("hidden_articles", [])
        
        # Sadece dict formatındaki geçerli verileri VE url'si EŞLEŞMEYENLERİ tut
        valid_hidden = [
            art for art in raw_hidden 
            if isinstance(art, dict) and art.get("url") != url
        ]
        
        session["hidden_articles"] = valid_hidden
        session.modified = True
        
    return redirect(request.referrer or "/gizlenen-haberler")

@app.route('/gizlenen-haberler')
def gizlenen_haberler():
    raw_hidden = session.get("hidden_articles", [])
    valid_hidden = [art for art in raw_hidden if isinstance(art, dict)]
    return render_template('gizlenenler.html', articles=valid_hidden)
# -------------------------------------------------------------------

if __name__ == "__main__":
    create_tables()
    app.run(debug=True)