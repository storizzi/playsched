# PlaySched Roadmap

A few ideas for future version - feel free to suggest things yourself! This is starting out as scratching an itch, but eventually it will hopefully start expanding out to a richer audio media thingy.

## Spotify Related

* Create zsh script and crontab file to use with crontab to (every 2 hours) update spotify played tracks, and (every day) update playlists with changes
* Shared functionality - Share functionality between command line tool and front-end and create libraries of that shared functionality
* Play spotify playlists not linked to user
* Play individual tracks from playlists
* Create new playlist from tracks from multiple playlists
* Optionally move token cache into database
* Optionally move environment information into database
* Multiple Spotify accounts from one dashboard

## Non Spotify related

* Scan local files and add details to database
* Compare spotify files with local files - e.g. if want to play local files instead of spotify files when have both or source music outside of spotify
* Local streaming server mode - play local files and playlists
* Include scheduling of local playlists
* Mixed playlist - play from local playlist and from Spotify mixed up
  * This is so when Spotify suddenly stop having your favourite tracks available, you can always buy them, store the tracks on your computer, and fill in the gaps. Hopefully, we can have a feature to detect where this happens, and let you know you have tracks that have gone missing from your playlists (typically due to some kind of rights issue). Very annoying.
* Include tracks (and maybe playlists) from Suno.ai
* Include tracks (and maybe playlists) stored in URLs (mayble download / track such playlists)
* Podcasts - incl. downloading episodes for later playback
* Include audio from Plex servers (maybe others)
* Identify metadata for tracks - e.g. from external sources
* Volume leveling
* Create playlists / virtual playlists based on factors such as 'eras' / 'genres' / plays / playlist name pattern etc. Allow these to be used for random play based on these factors rather than having a set list of tracks.
* Identify music / playlists prefer to play at certain times and create 'radio' that brings things in at these times to play

# General functionality

* Rename command line tool to be more generic
* Rename server starter
* Make it easy to create and start application without having command-line skills
* Play something between tracks on playlist (audible transition) - e.g. another playlist, a single track, a podcast etc.
* Webapp version so people can easily use this from a hosting provider rather than from home
* 