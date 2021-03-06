# Copyright 2014: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import ddt
import jsonschema

from rally.plugins.common.sla import iteration_time
from tests.unit import test


@ddt.ddt
class IterationTimeTestCase(test.TestCase):
    def test_config_schema(self):
        properties = {
            "max_seconds_per_iteration": 0
        }
        self.assertRaises(jsonschema.ValidationError,
                          iteration_time.IterationTime.validate, properties)

    def test_result(self):
        sla1 = iteration_time.IterationTime(42)
        sla2 = iteration_time.IterationTime(3.62)
        for sla in [sla1, sla2]:
            sla.add_iteration({"duration": 3.14})
            sla.add_iteration({"duration": 6.28})
        self.assertTrue(sla1.result()["success"])   # 42 > 6.28
        self.assertFalse(sla2.result()["success"])  # 3.62 < 6.28
        self.assertEqual("Passed", sla1.status())
        self.assertEqual("Failed", sla2.status())

    def test_result_no_iterations(self):
        sla = iteration_time.IterationTime(42)
        self.assertTrue(sla.result()["success"])

    def test_add_iteration(self):
        sla = iteration_time.IterationTime(4.0)
        self.assertTrue(sla.add_iteration({"duration": 3.14}))
        self.assertTrue(sla.add_iteration({"duration": 2.0}))
        self.assertTrue(sla.add_iteration({"duration": 3.99}))
        self.assertFalse(sla.add_iteration({"duration": 4.5}))
        self.assertFalse(sla.add_iteration({"duration": 3.8}))

    @ddt.data([[1.0, 2.0, 1.5, 4.3],
               [2.1, 3.4, 1.2, 6.3, 7.2, 7.0, 1.],
               [1.1, 1.1, 2.2, 2.2, 3.3, 4.3]])
    def test_merge(self, durations):

        single_sla = iteration_time.IterationTime(4.0)

        for dd in durations:
            for d in dd:
                single_sla.add_iteration({"duration": d})

        slas = [iteration_time.IterationTime(4.0) for _ in durations]

        for idx, sla in enumerate(slas):
            for duration in durations[idx]:
                sla.add_iteration({"duration": duration})

        merged_sla = slas[0]
        for sla in slas[1:]:
            merged_sla.merge(sla)

        self.assertEqual(single_sla.success, merged_sla.success)
        self.assertEqual(single_sla.max_iteration_time,
                         merged_sla.max_iteration_time)
