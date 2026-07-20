# Instagram Reels Automation — One-Time Setup

Two independent things need setting up before Instagram cross-posting works:
(1) a Meta Developer app + Instagram Business account, (2) a Cloudflare R2
bucket for temporary video hosting. Both are free.

## Part 1: Instagram / Meta

1. **Convert Instagram to a Business/Creator account**: Instagram app → your
   profile → menu → Settings and privacy → **Professional account** → switch
   to Business or Creator.
2. **Link it to a Facebook Page**: from that same Professional account
   screen, connect (or create) a Facebook Page. If you don't have one:
   facebook.com/pages/create.
3. **Create a Meta Developer app**: developers.facebook.com/apps → Create App
   → type "Other" → use case "Business" → name it anything.
4. **Add the Instagram product**: in the app dashboard, Add Product →
   Instagram (Graph API) → Set up. Note the **App ID** and **App Secret**
   under App Settings → Basic.
5. **Add yourself as an Instagram Tester** (required while the app is in
   Development Mode — only tester accounts can be posted to before Meta's
   App Review): App Roles → Roles → Add People → Instagram Tester → your IG
   account. Then, in Instagram: Settings and privacy → Apps and websites →
   Tester Invites → accept.
6. **Generate a token**: Graph API Explorer
   (developers.facebook.com/tools/explorer) → select your app + Page →
   request permissions `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement` → Generate Access Token.
7. Run `python setup_instagram_auth.py` and paste in the App ID, App Secret,
   and the token from step 6 — it handles the long-lived token exchange and
   writes everything to `.env` automatically.

## Part 2: Cloudflare R2 (temporary video hosting)

Instagram's API needs a public URL per video; R2's free tier (10GB storage,
no egress fees) covers this easily at this project's volume.

1. Sign up at dash.cloudflare.com (free) → enable R2 from the sidebar.
2. Create a bucket (e.g. `reels-temp`).
3. R2 → Manage API Tokens → Create API Token → permissions "Object Read &
   Write", scoped to that bucket → note the **Access Key ID** and **Secret
   Access Key** shown (only shown once).
4. Note your **Account ID** (shown in the R2 dashboard sidebar).
5. Add these 4 values to `.env` (or paste them into the dashboard's Instagram
   tab settings once built): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`.

No public bucket access or custom domain is needed — the pipeline generates
a short-lived presigned URL per upload, valid for 1 hour, which is deleted
right after Instagram finishes processing the video.
