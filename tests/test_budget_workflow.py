"""Per-task token budgets at the real call gates, using fake providers and disposable repositories."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app/backend'),str(ROOT/'pilot'),str(ROOT/'tests')]
import budget
import changes
from service import Application
import test_change_workflow
import test_task_workflow


def consume_all_but(app, task_id, keep):
    """Charge external use so that only `keep` tokens of the task budget remain."""
    task=next(t for p in app.state['projects'].values() for i,t in p.get('tasks',{}).items() if i==task_id)
    totals=budget.ledger(app.state,task_id,task['token_budget'])
    app.state['usage'].append({'id':'fixture-'+str(len(app.state['usage'])),'role':'Fixture','task_id':task_id,'tokens':None,
                               'outcome':'completed','charge_kind':'reported','charge':totals['remaining']-keep,'estimate':0})


class TeamBudgetTests(unittest.TestCase):
    setUp=test_task_workflow.TaskWorkflowTests.setUp
    git=test_task_workflow.TaskWorkflowTests.git
    setup_app=test_task_workflow.TaskWorkflowTests.setup_app
    ref=test_task_workflow.TaskWorkflowTests.ref
    create=test_task_workflow.TaskWorkflowTests.create
    select=test_task_workflow.TaskWorkflowTests.select
    propose=test_task_workflow.TaskWorkflowTests.propose
    start=test_task_workflow.TaskWorkflowTests.start
    def task(self,tid=None):return self.app.state['projects'][self.pid]['tasks'][tid or self.a]
    def set_budget(self,value,tid=None):
        return self.app.handle('update_task',self.ref(tid,token_budget=value))

    def test_new_tasks_default_budget_and_plans_bind_it(self):
        self.setup_app()
        self.assertEqual(self.task()['token_budget'],budget.DEFAULT_BUDGET)
        self.assertEqual(self.app.public()['task']['token_budget'],budget.DEFAULT_BUDGET)
        plan=self.propose()
        self.assertEqual(plan['limits']['token_budget'],budget.DEFAULT_BUDGET)
        tokens=self.app.public()['task']['tokens']
        self.assertGreater(tokens['used'],0);self.assertEqual(tokens['estimated'],tokens['used'])
        self.assertEqual(self.app.public()['plan_budget']['calls'],len(plan['tasks'])+1)
        self.assertTrue(self.app.public()['plan_budget']['fits'])
        for bad in (0,-5,1.5,'10',True):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.set_budget(bad)

    def test_refused_planning_call_never_reaches_provider_and_keeps_the_message(self):
        self.setup_app();self.set_budget(1000)
        self.app.handle('chat',self.ref(scope='task',text='Plan within budget'));self.app.wait()
        self.assertEqual(self.provider.calls,[])
        state=self.app.public()
        self.assertIn('Token budget exhausted',state['error'])
        self.assertEqual(state['threads']['task'],[{'role':'user','text':'Plan within budget'}])
        self.assertEqual(next(t for t in state['tasks'] if t['id']==self.a)['status'],'budget_exhausted')
        self.assertEqual(budget.ledger(self.app.state,self.a)['entries'],[])

    def test_team_run_stops_budget_exhausted_with_completed_artifacts_preserved(self):
        self.setup_app();plan=self.propose();calls=len(self.provider.calls)
        def squeeze(prompt):
            if 'Role: Researcher' in prompt:consume_all_but(self.app,self.a,1)
        self.provider.before=squeeze
        run=self.start(plan)
        self.assertEqual(run['stage'],'budget_exhausted')
        self.assertEqual(len(self.provider.calls),calls+1)
        self.assertIn('researcher',run['results'])
        statuses={t['id']:t['status'] for t in run['tasks']}
        self.assertEqual(statuses['researcher'],'done');self.assertEqual(statuses['reviewer'],'blocked')
        self.assertEqual([j['id'] for j in run['jobs']],['researcher'])
        self.assertIn('Token budget exhausted',self.app.public()['error'])
        self.assertIsNone(self.app.public()['active'])

    def test_start_is_blocked_outright_when_no_call_can_fit(self):
        self.setup_app();plan=self.propose();calls=len(self.provider.calls)
        consume_all_but(self.app,self.a,10)
        with self.assertRaisesRegex(ValueError,'Token budget exhausted'):
            self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']))
        self.assertEqual(len(self.provider.calls),calls);self.assertEqual(self.task()['run_ids'],[])
        self.assertIsNotNone(self.app.public()['pending'])
        self.assertFalse(self.app.public()['plan_budget']['first_fits'])

    def test_budget_edit_clears_unstarted_plan_and_stale_start_fails(self):
        self.setup_app();plan=self.propose()
        self.set_budget(400000)
        self.assertIsNone(self.app.public()['pending'])
        with self.assertRaises(ValueError):
            self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']))
        plan=self.propose();self.assertEqual(plan['limits']['token_budget'],400000)
        self.task()['token_budget']=300000  # A tampered or out-of-band change must not reuse the approval.
        with self.assertRaisesRegex(ValueError,'budget'):
            self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']))

    def test_restart_while_reserved_charges_the_estimate(self):
        self.setup_app();plan=self.propose()
        self.provider.block='Role: Researcher'
        self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']))
        self.assertTrue(self.provider.entered.wait(4))
        saved=json.loads((self.app.storage/'state.json').read_text())
        held=[e for e in saved['usage'] if e.get('charge_kind')=='reserved']
        self.assertEqual(len(held),1);self.assertEqual(held[0]['task_id'],self.a)
        reopened=Application(self.app.storage,provider=self.provider)
        entry=next(e for e in reopened.state['usage'] if e['id']==held[0]['id'])
        self.assertEqual((entry['charge_kind'],entry['charge'],entry['outcome']),('estimated',entry['estimate'],'interrupted'))
        self.provider.release.set();self.app.wait()

    def test_legacy_budgetless_task_and_pending_plan_remain_valid_and_unlimited(self):
        self.setup_app();raw=self.task();raw['token_budget']=None
        plan=self.propose();self.assertNotIn('token_budget',plan['limits'])
        self.assertIsNone(self.app.public()['plan_budget'])
        run=self.start(plan);self.assertEqual(run['stage'],'completed')
        self.assertIsNone(self.app.public()['task']['tokens']['budget'])

    def test_project_and_workspace_conversations_are_never_refused(self):
        self.setup_app();self.provider.answer=True
        for tid in (self.a,self.b):self.task(tid)['token_budget']=1
        self.select(None)
        self.app.handle('chat',{'scope':'workspace','text':'Compare priorities'});self.app.wait()
        self.assertFalse(self.app.public()['error'])
        self.app.handle('chat',{'scope':'project','project_id':self.pid,'task_id':None,'text':'General question'});self.app.wait()
        self.assertFalse(self.app.public()['error'],self.app.public()['error'])
        self.assertEqual(len(self.provider.calls),2)


class ChangeBudgetTests(unittest.TestCase):
    setUp=test_change_workflow.WorkflowTests.setUp
    git=test_change_workflow.WorkflowTests.git
    commit_files=test_change_workflow.WorkflowTests.commit_files
    setup_app=test_change_workflow.WorkflowTests.setup_app
    check=test_change_workflow.WorkflowTests.check
    propose=test_change_workflow.WorkflowTests.propose
    start=test_change_workflow.WorkflowTests.start
    ref=test_change_workflow.WorkflowTests.ref
    def task(self):return self.app.state['projects'][self.pid]['tasks'][self.tid]
    def check_ref(self):return copy.deepcopy(self.app.public()['run']['action_refs']['approve_checks'])

    def test_check_approval_binds_the_current_budget_and_rejects_stale_budget(self):
        self.setup_app();paused=self.start()
        self.assertEqual(paused['stage'],'awaiting_test_approval')
        reference=self.check_ref();self.assertEqual(reference['token_budget'],budget.DEFAULT_BUDGET)
        self.assertTrue(paused['budget_projection']['fits']);self.assertEqual(paused['budget_projection']['calls'],3)
        self.app.handle('update_task',dict(project_id=self.pid,task_id=self.tid,token_budget=300000))
        with self.assertRaisesRegex(ValueError,'budget'):self.app.handle('approve_checks',reference)
        self.assertEqual(self.processes,[])
        fresh=self.check_ref();self.assertEqual(fresh['token_budget'],300000)
        self.app.handle('approve_checks',fresh);self.app.wait()
        run=self.app.public()['run']
        self.assertEqual(run['stage'],'ready_to_apply');self.assertEqual(run['test_approval']['token_budget'],300000)

    def test_check_approval_is_blocked_outright_when_the_first_review_call_cannot_fit(self):
        self.setup_app();self.start();calls=len(self.provider.calls)
        consume_all_but(self.app,self.tid,10)
        with self.assertRaisesRegex(ValueError,'Token budget exhausted'):self.app.handle('approve_checks',self.check_ref())
        run=self.app.public()['run']
        self.assertEqual(run['stage'],'awaiting_test_approval');self.assertIsNone(run['test_approval'])
        self.assertEqual(self.processes,[]);self.assertEqual(len(self.provider.calls),calls)

    def test_change_run_stops_after_checks_with_candidate_and_results_preserved(self):
        self.setup_app();paused=self.start();calls=len(self.provider.calls)
        def squeeze(prompt):
            if 'Role: Tester' in prompt:consume_all_but(self.app,self.tid,1)
        self.provider.before=squeeze
        self.app.handle('approve_checks',self.check_ref());self.app.wait()
        run=self.app.public()['run']
        self.assertEqual(run['stage'],'budget_exhausted')
        self.assertEqual(len(self.provider.calls),calls+1)
        self.assertEqual(set(run['checks']['results']),set(changes.CHECKS))
        self.assertEqual(run['candidate']['digest'],paused['candidate']['digest'])
        self.assertIn('test',run['results']);self.assertNotIn('review',run['results'])
        self.assertFalse(run['can_apply_changes'])

    def test_generation_stops_budget_exhausted_without_a_candidate(self):
        self.setup_app();plan=self.propose();calls=len(self.provider.calls)
        consume_all_but(self.app,self.tid,budget.estimate_chars(0,'Implementer')+1)
        run=self.start(plan)
        self.assertEqual(run['stage'],'budget_exhausted');self.assertEqual(len(self.provider.calls),calls)
        self.assertFalse(run['candidate']['frozen']);self.assertEqual(self.processes,[])


if __name__=='__main__':
    unittest.main()
