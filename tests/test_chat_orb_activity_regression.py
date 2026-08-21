import unittest
from pathlib import Path


class ChatOrbActivityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = Path('frontend/project_workspace.js').read_text(encoding='utf-8')

    def test_chat_replies_reuse_selected_agent_orb_identity(self):
        raw=self.raw
        self.assertIn('window.__agentieChatOrbActivity',raw)
        self.assertIn("row.querySelector('.agent-orb')",raw)
        self.assertIn("row.dataset.chatAgentId=data.id",raw)
        self.assertIn("row.dataset.chatAgentName=data.name",raw)
        self.assertIn("orb.style.background=data.color",raw)
        self.assertIn("orb.textContent=data.initials",raw)

    def test_assistant_reply_renderer_is_enhanced_not_replaced(self):
        raw=self.raw
        self.assertIn('const previousAdd=window.addAssistant',raw)
        self.assertIn('window.addAssistant=function(message,card)',raw)
        self.assertIn('const result=previousAdd(message,card)',raw)
        self.assertIn("row.classList.add('agent-reply-orb')",raw)

    def test_working_and_queued_states_are_visible_and_animated(self):
        raw=self.raw
        self.assertIn('@keyframes agentieOrbWork',raw)
        self.assertIn('@keyframes agentieOrbPulse',raw)
        self.assertIn("label.textContent=clean==='working'?'Working'",raw)
        self.assertIn("row.classList.toggle('agent-orb-working'",raw)
        self.assertIn("row.classList.toggle('agent-orb-queued'",raw)

    def test_background_jobs_keep_orb_state_tied_to_job_id(self):
        raw=self.raw
        self.assertIn('function jobId(card)',raw)
        self.assertIn('row.dataset.chatJobId=id',raw)
        self.assertIn('function syncJob(id,state,name)',raw)
        self.assertIn("messages.querySelectorAll('.assistant-row[data-chat-job-id]')",raw)

    def test_delegated_background_work_has_live_chat_indicator(self):
        raw=self.raw
        self.assertIn('function syncBackground()',raw)
        self.assertIn("info.activity==='queued'?`${info.name} is queued…`:`${info.name} is working…`",raw)
        self.assertIn("row.className='assistant-row agent-background-working'",raw)
        self.assertIn('setInterval(syncBackground,700)',raw)

    def test_mutation_observer_is_idempotent(self):
        raw=self.raw
        self.assertIn('row.dataset.chatOrbDecorated',raw)
        self.assertIn("if(!row.dataset.chatOrbDecorated)",raw)
        self.assertIn('requestAnimationFrame(()=>{queued=false;decorateExisting()})',raw)


if __name__=='__main__':
    unittest.main()
