# Footage library

The editor agent cuts **your own GTA 6 gameplay recordings** into every video.
Clips are not committed to git. They are stored in a GitHub Release tagged `footage`, and every run downloads and caches them.

## How to add clips
1. Record gameplay on PS5 or Xbox with the Share/Capture button. 30–120 second clips work best. Save them as MP4.
2. **Name each file with tags** that describe what's on screen. The agent matches these tags to the script's scenes:
   - `car_chase_police_night_01.mp4`
   - `vice_city_beach_sunset_02.mp4`
   - `jason_lucia_cutscene_story_03.mp4`
   - `map_overview_aerial_04.mp4`
   - `money_heist_bank_05.mp4`
   - `boat_swamp_leonida_06.mp4`
3. Upload them to the release:
   ```bash
   gh release create footage --title "Footage library" --notes "GTA 6 clips"   # first time only
   gh release upload footage *.mp4
   ```
   Or use GitHub web → Releases → `footage` → Edit → drag files in. Each file can be up to 2 GB.

Add 10–20 new clips every week. Each clip's use count is tracked in `state/footage_usage.json`, so fresh clips get picked first.
Fresh footage is also what keeps the channel clear of YouTube's "reused / inauthentic content" monetisation rules.

**Do not** upload Rockstar trailers or other creators' videos. Content ID claims and strikes would hit the channel.
