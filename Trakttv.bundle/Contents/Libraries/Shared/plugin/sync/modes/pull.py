from plugin.sync.core.enums import SyncMode, SyncMedia
from plugin.sync.modes.core.base import Mode, TRAKT_DATA_MAP

from plex_database.models import LibrarySectionType, LibrarySection
import logging

log = logging.getLogger(__name__)


class Base(Mode):
    mode = SyncMode.Pull

    def step(self, pending, data, key):
        if key not in pending[data]:
            return

        # Increment one step
        self.current.progress.step()

        # Remove from `pending` dictionary
        del pending[data][key]


class Movies(Base):
    def run(self):
        # Retrieve movie sections
        p_sections = self.plex.library.sections(
            LibrarySectionType.Movie,
            LibrarySection.id
        ).tuples()

        # Fetch movies with account settings
        p_items = self.plex.library.movies.mapped(
            p_sections,
            account=self.current.account.plex.id,
            parse_guid=True
        )

        # Calculate total number of movies
        pending = {}
        total = 0

        for data in TRAKT_DATA_MAP[SyncMedia.Movies]:
            if data not in pending:
                pending[data] = {}

            for pk in self.trakt[(SyncMedia.Movies, data)]:
                pending[data][pk] = False
                total += 1

        # Task started
        self.current.progress.start(total)

        for rating_key, p_guid, p_item in p_items:
            key = (p_guid.agent, p_guid.sid)

            # Try retrieve `pk` for `key`
            pk = self.trakt.table.get(key)

            if pk is None:
                # No `pk` found
                continue

            for data in TRAKT_DATA_MAP[SyncMedia.Movies]:
                t_movie = self.trakt[(SyncMedia.Movies, data)].get(pk)

                self.execute_handlers(
                    SyncMedia.Movies, data,
                    rating_key=rating_key,

                    p_item=p_item,
                    t_item=t_movie
                )

                # Increment one step
                self.step(pending, data, pk)

        # Task stopped
        log.debug('Pending: %r', pending)

        self.current.progress.stop()


class Shows(Base):
    def run(self):
        # Retrieve show sections
        p_sections = self.plex.library.sections(
            LibrarySectionType.Show,
            LibrarySection.id
        ).tuples()

        # Fetch episodes with account settings
        p_shows, p_seasons, p_episodes = self.plex.library.episodes.mapped(
            p_sections,
            account=self.current.account.plex.id,
            parse_guid=True
        )

        # TODO process shows, seasons

        # Calculate total number of episodes
        pending = {}
        total = 0

        for data in TRAKT_DATA_MAP[SyncMedia.Episodes]:
            t_episodes = [
                (key, se, ep)
                for key, t_show in self.trakt[(SyncMedia.Episodes, data)].items()
                for se, t_season in t_show.seasons.items()
                for ep in t_season.episodes.iterkeys()
            ]

            if data not in pending:
                pending[data] = {}

            for key in t_episodes:
                pending[data][key] = False
                total += 1

        # Task started
        self.current.progress.start(total)

        # Process episodes
        for ids, p_guid, (season_num, episode_num), p_show, p_season, p_episode in p_episodes:
            key = (p_guid.agent, p_guid.sid)

            # Try retrieve `pk` for `key`
            pk = self.trakt.table.get(key)

            if pk is None:
                # No `pk` found
                continue

            if not ids.get('episode'):
                # Missing `episode` rating key
                continue

            for data in TRAKT_DATA_MAP[SyncMedia.Episodes]:
                t_show = self.trakt[(SyncMedia.Episodes, data)].get(pk)

                if t_show is None:
                    # Unable to find matching show in trakt data
                    continue

                t_season = t_show.seasons.get(season_num)

                if t_season is None:
                    # Unable to find matching season in `t_show`
                    continue

                t_episode = t_season.episodes.get(episode_num)

                if t_episode is None:
                    # Unable to find matching episode in `t_season`
                    continue

                self.execute_handlers(
                    SyncMedia.Episodes, data,
                    rating_key=ids['episode'],

                    p_item=p_episode,
                    t_item=t_episode
                )

                # Increment one step
                self.step(pending, data, (pk, season_num, episode_num))

        # Task stopped
        log.debug('Pending: %r', pending)

        self.current.progress.stop()


class Pull(Mode):
    mode = SyncMode.Pull

    children = [
        Movies,
        Shows
    ]

    def run(self):
        # Fetch changes from trakt.tv
        self.trakt.refresh()

        # Build key table for lookups
        self.trakt.build_table()

        # Run children
        self.execute_children()
