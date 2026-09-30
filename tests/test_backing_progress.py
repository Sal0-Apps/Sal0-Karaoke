import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'app'))
from backing_progress import vr_progress, read_progress_event
import backing_progress


class Bar:
    def __init__(self, iterable, **kwargs):
        self.iterable = iterable
    def __iter__(self):
        return iter(self.iterable)
    def close(self):
        pass


class BackingProgressTests(unittest.TestCase):
    def test_real_work_must_complete_before_progress_and_each_bar_has_own_phase(self):
        module = SimpleNamespace(tqdm=Bar)
        events, work = [], []
        def loading():
            for item in module.tqdm(range(4,0,-1)):
                work.append(('bands',item))
        def inference(*args):
            for item in module.tqdm(range(55)):
                work.append(('windows',item))
            for item in module.tqdm(range(0,55,1)):
                work.append(('prediction',item))
        model = SimpleNamespace(loading_mix=loading,inference_vr=inference,spec_to_wav=lambda _:None)
        with patch.object(backing_progress,'emit_progress',side_effect=lambda phase,percent:events.append((phase,percent,list(work)))):
            with vr_progress(model,module):
                model.loading_mix();model.inference_vr();model.spec_to_wav(None);model.spec_to_wav(None)
        first_inference = next(e for e in events if e[0]=='inference')
        self.assertEqual(first_inference[1],0)
        self.assertFalse(any(kind=='prediction' for kind,_ in first_inference[2]))
        at_end = next(e for e in events if e[:2]==('inference',100))
        self.assertEqual(sum(kind=='prediction' for kind,_ in at_end[2]),55)
        self.assertEqual([e[:2] for e in events if e[0]=='preparing_audio'],
                         [('preparing_audio',0),('preparing_audio',25),('preparing_audio',50),('preparing_audio',75),('preparing_audio',100)])
        self.assertEqual(sum(e[0]=='reconstructing' for e in events),1)
        self.assertIs(module.tqdm,Bar)
        self.assertIs(model.inference_vr,inference)

    def test_failed_prediction_never_reaches_one_hundred_and_restores_instrumentation(self):
        module = SimpleNamespace(tqdm=Bar)
        def inference():
            for _ in module.tqdm(range(2)):
                pass
            for _ in module.tqdm(range(2)):
                raise RuntimeError('prediction failed')
        model = SimpleNamespace(loading_mix=lambda:None,inference_vr=inference,spec_to_wav=lambda _:None)
        with patch.object(backing_progress,'emit_progress') as notify:
            with self.assertRaises(RuntimeError), vr_progress(model,module):
                model.inference_vr()
        self.assertNotIn(('inference',100), [c.args for c in notify.call_args_list])
        self.assertIs(module.tqdm,Bar)

    def test_unrelated_logs_and_invalid_events_are_ignored(self):
        for line in ['100%|55/55','SAL0_BVE_PROGRESS []','SAL0_BVE_PROGRESS {"phase":"inference","percent":101}',
                     'SAL0_BVE_PROGRESS {"phase":"inference","percent":true}',
                     'SAL0_BVE_PROGRESS {"phase":"other","percent":50}']:
            self.assertIsNone(read_progress_event(line))
        self.assertEqual(read_progress_event('SAL0_BVE_PROGRESS {"phase":"inference","percent":0}'),('inference',0))


if __name__=='__main__':
    unittest.main()
