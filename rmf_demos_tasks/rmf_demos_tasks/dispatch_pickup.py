#!/usr/bin/env python3

# Copyright 2021 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import uuid
import argparse
import json
import asyncio

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_system_default
from rclpy.qos import QoSProfile
from rclpy.qos import QoSHistoryPolicy as History
from rclpy.qos import QoSDurabilityPolicy as Durability
from rclpy.qos import QoSReliabilityPolicy as Reliability

from rmf_task_msgs.msg import ApiRequest, ApiResponse


###############################################################################

class TaskRequester(Node):

    def __init__(self, argv=sys.argv):
        super().__init__('task_requester')
        parser = argparse.ArgumentParser()
        parser.add_argument('-p', '--pickups', required=True,
                            type=str, nargs='+',
                            help="Pickup names")
        parser.add_argument('-ph', '--pickup_handlers', required=True,
                            type=str, nargs='+',
                            help="Pickup handler names")
        parser.add_argument('-pp', '--pickup_payloads',
                            type=str, nargs='+', default=[],
                            help="Pickup payload [sku,quantity sku2,qty...]")
        parser.add_argument('-F', '--fleet', type=str,
                            help='Fleet name, should define tgt with robot')
        parser.add_argument('-R', '--robot', type=str,
                            help='Robot name, should define tgt with fleet')
        parser.add_argument('-st', '--start_time',
                            help='Start time from now in secs, default: 0',
                            type=int, default=0)
        parser.add_argument('-pt', '--priority',
                            help='Priority value for this request',
                            type=int, default=0)
        parser.add_argument("--use_sim_time", action="store_true",
                            help='Use sim time, default: false')

        self.args = parser.parse_args(argv[1:])
        self.response = asyncio.Future()

        # check user delivery arg inputs
        if (len(self.args.pickups) != len(self.args.pickup_handlers)):
            self.get_logger().error(
                "Invalid pickups, [-p] should have the same length as [-ph]")
            parser.print_help()
            sys.exit(1)

        transient_qos = QoSProfile(
            history=History.KEEP_LAST,
            depth=1,
            reliability=Reliability.RELIABLE,
            durability=Durability.TRANSIENT_LOCAL)

        self.pub = self.create_publisher(
          ApiRequest, 'task_api_requests', transient_qos)

        # enable ros sim time
        if self.args.use_sim_time:
            self.get_logger().info("Using Sim Time")
            param = Parameter("use_sim_time", Parameter.Type.BOOL, True)
            self.set_parameters([param])

        # Construct task
        msg = ApiRequest()
        msg.request_id = "pickup_" + str(uuid.uuid4())
        payload = {}
        if self.args.fleet and self.args.robot:
            self.get_logger().info("Using 'robot_task_request'")
            payload["type"] = "robot_task_request"
            payload["robot"] = self.args.robot
            payload["fleet"] = self.args.fleet
        else:
            self.get_logger().info("Using 'dispatch_task_request'")
            payload["type"] = "dispatch_task_request"
        request = {}

        # Set task request start time
        now = self.get_clock().now().to_msg()
        now.sec = now.sec + self.args.start_time
        start_time = now.sec * 1000 + round(now.nanosec/10**6)
        request["unix_millis_earliest_start_time"] = start_time

        def __create_pickup_desc(index):
            if index < len(self.args.pickup_payloads):
                sku_qty = self.args.pickup_payloads[index].split(',')
                assert len(sku_qty) == 3, \
                    "please specify sku and qty for pickup payload"
                payload = [{"sku": sku_qty[0],
                            "quantity": int(sku_qty[1]), "compartment": sku_qty[2]}]
            else:
                payload = []

            return {
                    "place": self.args.pickups[index],
                    "handler": self.args.pickup_handlers[index],
                    "payload": payload
                    }

        # Define multi_delivery with request category compose
        request["category"] = "compose"

        # Define task request description with phases
        description = {}  # task_description_Compose.json
        description["category"] = "multi_delivery"
        description["phases"] = []
        activities = []
        # Add each pickup
        for i in range(0, len(self.args.pickups)):
            activities.append({
                "category": "pickup",
                "description": __create_pickup_desc(i)})
        # Add activities to phases
        description["phases"].append(
            {"activity": {
                "category": "sequence",
                "description": {"activities": activities}}})

        request["description"] = description
        payload["request"] = request
        msg.json_msg = json.dumps(payload)


        request["description"] = description
        payload["request"] = request
        msg.json_msg = json.dumps(payload)

        def receive_response(response_msg: ApiResponse):
            if response_msg.request_id == msg.request_id:
                self.response.set_result(json.loads(response_msg.json_msg))

        self.sub = self.create_subscription(
            ApiResponse, 'task_api_responses', receive_response, 10
        )

        print(f"Json msg payload: \n{json.dumps(payload, indent=2)}")

        self.pub.publish(msg)


###############################################################################


def main(argv=sys.argv):
    rclpy.init(args=sys.argv)
    args_without_ros = rclpy.utilities.remove_ros_args(sys.argv)

    task_requester = TaskRequester(args_without_ros)
    rclpy.spin_until_future_complete(
        task_requester, task_requester.response, timeout_sec=5.0)
    if task_requester.response.done():
        print(f'Got response:\n{task_requester.response.result()}')
    else:
        print('Did not get a response')
    rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
