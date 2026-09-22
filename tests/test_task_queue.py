import tempfile
import unittest
from pathlib import Path

from src.rating_overlay.task_queue import TaskQueue


class TaskQueueTest(unittest.TestCase):
    def test_unfinished_task_is_requeued_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tasks.sqlite3'
            queue = TaskQueue(path)
            job_id = queue.add('imdb', {'mode': 'ratings'})
            self.assertEqual(queue.claim()['id'], job_id)
            queue.close()
            restarted = TaskQueue(path)
            restarted.resume()
            self.assertEqual(restarted.claim()['payload'], {'mode': 'ratings'})
            restarted.finish(job_id)
            self.assertEqual(restarted.list()[0]['status'], 'completed')
            restarted.close()


if __name__ == '__main__':
    unittest.main()
