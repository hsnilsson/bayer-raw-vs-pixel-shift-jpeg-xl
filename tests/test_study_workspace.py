"""Portable workspace boundaries must protect a nested private archive."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class WorkspaceBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.repo=self.base/'project'
        self.archive=self.repo/'archive'
        self.scratch=self.base/'scratch'
        config={'paths':{'archive':str(self.archive),'scratch':str(self.scratch)}}
        with patch.object(Path,'read_text',return_value=json.dumps(config)):
            runtime=runpy.run_path(str(ROOT/'scripts/study_runtime.py'))
        self.guard=runtime['assert_write']
        self.guard.__globals__.update(REPO=self.repo,WORK=self.repo/'work',ARCHIVE=self.archive,SCRATCH=self.scratch)

    def test_nested_archive_is_not_writable_through_project_boundary(self):
        with self.assertRaises(PermissionError):
            self.guard(self.archive/'records/measurements.json')

    def test_working_results_and_dedicated_scratch_are_writable(self):
        self.guard(self.repo/'results/new.json')
        self.guard(self.scratch/'decoded.ppm')

    def test_subprocess_pipe_file_descriptors_are_allowed(self):
        self.guard(3)

    def test_parent_traversal_cannot_escape_workspace(self):
        with self.assertRaises(PermissionError):
            self.guard(self.repo/'..'/'unrelated.txt')

    def test_scratch_setting_cannot_target_archive_or_project_root(self):
        module=runpy.run_path(str(ROOT/'scripts/study_workspace.py'))
        resolve=module['scratch_path']
        resolve.__globals__.update(ROOT=self.repo,ARCHIVE=self.archive)
        for value in (self.repo,self.archive,self.repo/'.git/objects',Path(self.repo.anchor)):
            with self.subTest(value=value),self.assertRaises(ValueError):
                resolve(value)
        self.assertEqual(resolve('work/scratch'),(self.repo/'work/scratch').resolve())


if __name__=='__main__':
    unittest.main()
