"""Proposal regression/negative-security checks. Offline results are not native acceptance."""
import copy
import json
import unittest
from . import policy
from .offline_filter import compile_bpf,verdict,ALLOW,ERRNO


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.bpf,cls.lib=compile_bpf()
    def call(self,name,args=(),arch=0xc000003e):
        nr=self.lib.seccomp_syscall_resolve_name(name.encode())
        return verdict(self.bpf,nr,args,arch)
    def test_exact_reviewed_proposal(self):self.assertEqual(policy.validate()['status'],'PASS')
    def test_baseline_rules_remain_identical(self):
        self.assertEqual(policy.build()['syscalls'][:-5],policy.baseline()['syscalls'])
    def test_only_five_new_rules(self):self.assertEqual(len(policy.build()['syscalls'])-len(policy.baseline()['syscalls']),5)
    def test_chromium_exact_clone_operations_allowed(self):
        for flags in policy.CLONE_VALUES:
            with self.subTest(flags=flags):self.assertEqual(self.call('clone',[flags]),ALLOW)
    def test_chromium_nested_userns_allowed(self):self.assertEqual(self.call('unshare',[policy.NEWUSER]),ALLOW)
    def test_chromium_filesystem_sandbox_call_allowed(self):self.assertEqual(self.call('chroot',[0]),ALLOW)
    def test_extra_namespace_or_control_bits_denied(self):
        for extra in (0x20000,0x4000000,0x8000000,0x2000000,0x100000000,0x10000,0x80000000):
            with self.subTest(extra=extra):self.assertEqual(self.call('clone',[policy.NEWUSER|17|extra]),ERRNO|1)
    def test_partial_zygote_namespace_sets_denied(self):
        for flags in (policy.NEWUSER|policy.NEWNET|17,policy.NEWUSER|policy.NEWPID|17,policy.NEWNET|17):
            with self.subTest(flags=flags):self.assertEqual(self.call('clone',[flags]),ERRNO|1)
    def test_namespace_join_and_mount_calls_denied(self):
        for name in ('setns','mount','umount2','pivot_root','open_tree','fsopen','move_mount'):
            with self.subTest(name=name):self.assertEqual(self.call(name),ERRNO|1)
    def test_kernel_attack_surface_calls_stay_denied(self):
        for name in ('bpf','keyctl','perf_event_open','init_module','finit_module','iopl'):
            with self.subTest(name=name):self.assertEqual(self.call(name),ERRNO|1)
    def test_unshare_other_namespaces_and_combinations_denied(self):
        for flags in (0,policy.NEWNET,policy.NEWPID,0x20000,0x4000000,policy.NEWUSER|policy.NEWNET,policy.NEWUSER|0x20000):
            with self.subTest(flags=flags):self.assertEqual(self.call('unshare',[flags]),ERRNO|1)
    def test_clone3_keeps_enosys_fallback(self):self.assertEqual(self.call('clone3'),ERRNO|38)
    def test_compatibility_architectures_rejected(self):
        for arch in (0x40000003,0xc00000b7):self.assertNotEqual(self.call('read',arch=arch),ALLOW)
        self.assertNotEqual(verdict(self.bpf,0x40000000),ALLOW)  # x32 syscall ABI
    def test_normal_runtime_calls_remain_allowed(self):
        for name in ('read','write','exit_group','futex','capget','capset'):
            with self.subTest(name=name):self.assertEqual(self.call(name),ALLOW)
    def test_broad_namespace_allowance_rejected(self):
        p=policy.build();p['syscalls'].append(dict(names=['clone','unshare','setns'],action='SCMP_ACT_ALLOW'))
        with self.assertRaises(ValueError):policy.validate(p)
    def test_default_allow_and_compat_abi_mutations_rejected(self):
        for key,value in [('defaultAction','SCMP_ACT_ALLOW'),('archMap',policy.baseline()['archMap'])]:
            p=policy.build();p[key]=value
            with self.assertRaises(ValueError):policy.validate(p)
    def test_removing_apparmor_denials_rejected(self):
        for line in ('  deny mount,','  deny /sys/kernel/security/** rwklx,','  userns,'):
            with self.assertRaises(ValueError):policy.validate(profile=policy.apparmor().replace(line,''))
    def test_apparmor_remains_enforcing_and_scoped(self):
        text=policy.apparmor()
        self.assertIn('profile '+policy.PROFILE+' flags=(attach_disconnected,mediate_deleted)',text)
        self.assertIn('abi <abi/4.0>',text)
        self.assertNotIn('flags=(unconfined)',text);self.assertNotIn('complain',text)
    def test_runtime_and_workflow_not_wired_to_proposal(self):
        root=policy.ROOT.parents[2]
        for name in ('validation/c3c/run.py','.github/workflows/c3c-security-validation.yml','deployment/c3c/supervisor.py'):
            self.assertNotIn(policy.PROFILE,(root/name).read_text())


if __name__=='__main__':unittest.main()
