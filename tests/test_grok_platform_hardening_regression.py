import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_lifecycle,agent_prompt,agent_registry,agent_teams,file_service,routine_engine,skill_portability,workflow_skills


class GrokPlatformHardeningRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.root=Path(self.temp.name);skills=self.root/'skills'
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',self.root),patch.object(agent_registry,'AGENTS_FILE',self.root/'agents.json'),
            patch.object(agent_prompt,'WORKSPACE',self.root),patch.object(agent_prompt,'PROMPTS_FILE',self.root/'agent_instruction_profiles.json'),
            patch.object(agent_teams,'WORKSPACE',self.root),patch.object(agent_teams,'TEAMS',self.root/'agent_teams.json'),
            patch.object(routine_engine,'WORKSPACE',self.root),patch.object(routine_engine,'ROUTINES',self.root/'routines.json'),patch.object(routine_engine,'RUNS',self.root/'routine_runs.json'),
            patch.object(workflow_skills,'WORKSPACE',self.root),patch.object(workflow_skills,'SKILLS_DIR',skills),
            patch.object(file_service,'WORKSPACE',self.root),patch.object(file_service,'UPLOADS',self.root/'uploads'),patch.object(file_service,'EXTRACTED',self.root/'extracted'),
        ]
        for item in self.patches:item.start()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_agent_delete_immediately_removes_raw_team_membership_and_lead(self):
        lead=agent_registry.create_agent('Cora','Coordinator',permissions={'delegate':True})['agent'];worker=agent_registry.create_agent('Ben','Worker')['agent'];team=agent_teams.create_team('Ops',[lead['id'],worker['id']],lead_agent_id=lead['id'])
        agent_registry.delete_agent(lead['id']);raw=agent_teams._load();saved=next(x for x in raw if x['id']==team['id'])
        self.assertNotIn(lead['id'],saved['member_ids']);self.assertIsNone(saved['lead_agent_id'])

    def test_duplicate_retargets_event_filter_that_referenced_source_agent(self):
        source=agent_registry.create_agent('Ada','Owner')['agent'];routine_engine.create_event_routine(name='Own Completed Skill',event_type='skill_run.completed',action='summarize it',owner_agent_id=source['id'],event_filters={'agent_id':source['id'],'status':'completed'})
        result=agent_lifecycle.duplicate_agent('Ada','Ava');cloned=result['routines'][0]
        self.assertEqual(cloned['owner_agent_id'],result['agent']['id']);self.assertEqual(cloned['event_filters']['agent_id'],result['agent']['id']);self.assertEqual(cloned['event_filters']['status'],'completed')

    def test_skill_import_rejects_malformed_list_field(self):
        file_service.ensure_dirs();payload={'format':skill_portability.FORMAT,'format_version':skill_portability.VERSION,'skill':{'name':'Bad Skill','steps':'not-a-list'}};path=file_service.UPLOADS/'bad-skill.json';path.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaises(ValueError):skill_portability.import_skill_from_upload(path.name)

    def test_coordinator_runtime_exposes_gap_analysis_without_hidden_role_checks(self):
        source=Path('agentie/tools/persistent_tools.py').read_text(encoding='utf-8')
        self.assertIn('analyze_team_capability_gap',source);self.assertIn('analyze_capability_gap',source);self.assertIn('permissions',source);self.assertNotIn('agent.get("role")',source);self.assertNotIn('agent.get("base")',source)


if __name__=='__main__':unittest.main()
