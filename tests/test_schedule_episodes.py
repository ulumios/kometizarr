import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.services import schedule


class CronEpisodesTest(unittest.TestCase):
    def test_include_episodes_reaches_the_task(self):
        with patch.object(schedule.tasks, 'enqueue', new=AsyncMock()) as enqueue:
            asyncio.run(schedule.cron_run_libraries(['Serien'], False, True))
        kind, payload = enqueue.call_args.args
        self.assertEqual((kind, payload['library_name'], payload['include_episodes'], payload['force']),
                         ('process', 'Serien', True, False))

    def test_reschedule_passes_the_setting(self):
        with patch.object(schedule, '_add_cron_job') as add, patch.object(schedule.scheduler, 'remove_all_jobs'):
            schedule.reschedule({'cron_normal': {'enabled': True, 'schedule': '0 3 * * *', 'libraries': [],
                                                 'include_episodes': True},
                                 'cron_force': {'enabled': True, 'schedule': '0 4 * * 0'}})
        self.assertEqual([call.args[-1] for call in add.call_args_list], [True, False])


if __name__ == '__main__':
    unittest.main()
