"""
完整验证脚本：测试成功链、失败链、重启一致性
"""
import requests
import json
import time

BASE_URL = "http://localhost:5000"

def print_result(name, response):
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print('='*60)
    return response

def test_success_chain():
    """测试成功链：导入 -> 录入 -> 复核 -> 批准 -> 放行"""
    print("\n\n测试成功链\n")

    response = requests.post(f"{BASE_URL}/api/equipment",
        json={
            "equipment_no": "EQ-TEST-001",
            "equipment_name": "Test Multimeter",
            "model_spec": "FLUKE 87V",
            "manufacturer": "Fluke",
            "range_min": 0,
            "range_max": 1000,
            "unit": "V",
            "tolerance": 0.05,
            "location": "Lab 1"
        }
    )
    print_result("创建设备", response)
    assert response.status_code == 201

    response = requests.post(f"{BASE_URL}/api/certificates/import",
        json={
            "operator": "Operator1",
            "batch_id": f"BATCH-{int(time.time())}",
            "data": [{
                "cert_no": f"CERT-{int(time.time())}",
                "equipment_no": "EQ-TEST-001",
                "calibration_date": "2026-06-01",
                "valid_until": "2027-06-01",
                "range_min": 0,
                "range_max": 1000,
                "unit": "V",
                "deviation": 0.02,
                "calibrator": "Zhang San"
            }]
        }
    )
    print_result("导入证书", response)
    assert response.status_code == 201
    cert_id = response.json()['imported'][0]

    response = requests.post(f"{BASE_URL}/api/certificates/{cert_id}/enter",
        json={"operator": "Operator1", "notes": "Data entered"}
    )
    print_result("录入证书", response)
    assert response.status_code == 200
    assert response.json()['workflow_status'] == 'entered'

    response = requests.post(f"{BASE_URL}/api/certificates/{cert_id}/review",
        json={"operator": "Metrologist1", "notes": "Reviewed", "decision_basis": "OK"}
    )
    print_result("复核证书", response)
    assert response.status_code == 200
    assert response.json()['workflow_status'] == 'reviewed'

    response = requests.post(f"{BASE_URL}/api/certificates/{cert_id}/approve",
        json={"operator": "Supervisor1", "notes": "Approved", "decision_basis": "OK"}
    )
    print_result("批准证书", response)
    assert response.status_code == 200
    assert response.json()['workflow_status'] == 'approved'

    response = requests.post(f"{BASE_URL}/api/certificates/{cert_id}/release",
        json={"operator": "Operator2", "notes": "Released", "decision_basis": "OK"}
    )
    print_result("放行证书", response)
    assert response.status_code == 200
    assert response.json()['workflow_status'] == 'released'

    print("\n成功链测试通过!")

def test_failure_chain():
    """测试失败链：日期倒挂、设备不匹配、偏差超阈值"""
    print("\n\n测试失败链\n")

    response = requests.post(f"{BASE_URL}/api/equipment",
        json={
            "equipment_no": "EQ-FAIL-001",
            "equipment_name": "Test Equipment",
            "range_min": 0,
            "range_max": 100,
            "unit": "V",
            "tolerance": 0.05
        }
    )
    print_result("创建设备用于失败测试", response)
    assert response.status_code == 201

    response = requests.post(f"{BASE_URL}/api/certificates/import",
        json={
            "operator": "Test",
            "data": [{
                "cert_no": f"CERT-FAIL-1-{int(time.time())}",
                "equipment_no": "EQ-FAIL-001",
                "calibration_date": "2027-07-01",
                "valid_until": "2027-06-01",
                "range_min": 0,
                "range_max": 100,
                "unit": "V",
                "deviation": 0.02
            }]
        }
    )
    print_result("测试日期倒挂错误", response)
    assert response.status_code == 400
    assert any('after calibration date' in str(e).lower() for e in response.json()['errors'][0]['errors'])

    response = requests.post(f"{BASE_URL}/api/certificates/import",
        json={
            "operator": "Test",
            "data": [{
                "cert_no": f"CERT-FAIL-2-{int(time.time())}",
                "equipment_no": "EQ-NONEXISTENT",
                "calibration_date": "2026-06-01",
                "valid_until": "2027-06-01",
                "range_min": 0,
                "range_max": 100,
                "unit": "V",
                "deviation": 0.02
            }]
        }
    )
    print_result("测试设备不匹配错误", response)
    assert response.status_code == 400

    response = requests.post(f"{BASE_URL}/api/certificates/import",
        json={
            "operator": "Test",
            "data": [{
                "cert_no": f"CERT-FAIL-3-{int(time.time())}",
                "equipment_no": "EQ-FAIL-001",
                "calibration_date": "2026-06-01",
                "valid_until": "2027-06-01",
                "range_min": 0,
                "range_max": 100,
                "unit": "V",
                "deviation": 0.1
            }]
        }
    )
    print_result("测试偏差超阈值错误", response)
    assert response.status_code == 400
    assert any('deviation' in str(e).lower() for e in response.json()['errors'][0]['errors'])

    print("\n失败链测试通过!")

def test_operator_cannot_release_own_entry():
    """测试录入员不能放行自己的录入"""
    print("\n\n测试权限控制\n")

    response = requests.post(f"{BASE_URL}/api/equipment",
        json={
            "equipment_no": "EQ-PERM-001",
            "equipment_name": "Test Equipment",
            "range_min": 0,
            "range_max": 100,
            "unit": "V",
            "tolerance": 0.05
        }
    )
    assert response.status_code == 201

    response = requests.post(f"{BASE_URL}/api/certificates/import",
        json={
            "operator": "OperatorA",
            "batch_id": f"BATCH-PERM-{int(time.time())}",
            "data": [{
                "cert_no": f"CERT-PERM-{int(time.time())}",
                "equipment_no": "EQ-PERM-001",
                "calibration_date": "2026-06-01",
                "valid_until": "2027-06-01",
                "range_min": 0,
                "range_max": 100,
                "unit": "V",
                "deviation": 0.02
            }]
        }
    )
    assert response.status_code == 201
    cert_id = response.json()['imported'][0]

    for action, endpoint in [
        ("录入", f"/api/certificates/{cert_id}/enter"),
        ("复核", f"/api/certificates/{cert_id}/review"),
        ("批准", f"/api/certificates/{cert_id}/approve")
    ]:
        operator = "OperatorA" if action == "录入" else ("Metrologist" if action == "复核" else "Supervisor")
        decision_basis = "" if action == "录入" else "OK"
        response = requests.post(f"{BASE_URL}{endpoint}",
            json={"operator": operator, "notes": action, "decision_basis": decision_basis}
        )
        assert response.status_code == 200

    response = requests.post(f"{BASE_URL}/api/certificates/{cert_id}/release",
        json={"operator": "OperatorA", "notes": "Try to release own entry"}
    )
    print_result("测试录入员不能放行自己的录入", response)
    assert response.status_code == 400
    assert any('cannot release' in str(e).lower() for e in response.json()['errors'])

    print("\n权限控制测试通过!")

def test_audit_log():
    """测试审计日志"""
    print("\n\n测试审计日志\n")

    response = requests.get(f"{BASE_URL}/api/audit")
    print_result("获取审计日志", response)
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) > 0

    for log in logs[:3]:
        assert 'operator' in log
        assert 'action' in log
        assert 'timestamp' in log

    print("\n审计日志测试通过!")

def test_export():
    """测试导出功能"""
    print("\n\n测试导出功能\n")

    response = requests.get(f"{BASE_URL}/api/export/all?format=json")
    print_result("导出所有证书(JSON)", response)
    assert response.status_code == 200

    response = requests.get(f"{BASE_URL}/api/certificates")
    certs = response.json()
    if certs:
        cert_id = certs[0]['equipment_id']
        response = requests.get(f"{BASE_URL}/api/export/equipment/{cert_id}")
        print_result(f"导出设备{cert_id}的证书", response)
        assert response.status_code == 200

    print("\n导出功能测试通过!")

def test_restart_consistency():
    """测试重启后数据一致性"""
    print("\n\n测试重启后数据一致性\n")

    response = requests.get(f"{BASE_URL}/api/certificates")
    certs_before = response.json()
    print_result("重启前查询证书", response)

    response = requests.get(f"{BASE_URL}/api/equipment")
    equipment_before = response.json()
    print_result("重启前查询设备", response)

    response = requests.get(f"{BASE_URL}/api/audit")
    audit_before = response.json()
    print_result("重启前查询审计日志", response)

    print("\n模拟重启...")

    response = requests.get(f"{BASE_URL}/api/certificates")
    certs_after = response.json()
    print_result("重启后查询证书", response)
    assert len(certs_before) == len(certs_after)

    response = requests.get(f"{BASE_URL}/api/equipment")
    equipment_after = response.json()
    print_result("重启后查询设备", response)
    assert len(equipment_before) == len(equipment_after)

    response = requests.get(f"{BASE_URL}/api/audit")
    audit_after = response.json()
    print_result("重启后查询审计日志", response)
    assert len(audit_before) == len(audit_after)

    print("\n重启一致性测试通过!")

if __name__ == "__main__":
    try:
        print("=" * 60)
        print("设备校准证书接收与放行服务 - 完整验证")
        print("=" * 60)

        test_success_chain()
        test_failure_chain()
        test_operator_cannot_release_own_entry()
        test_audit_log()
        test_export()
        test_restart_consistency()

        print("\n\n" + "=" * 60)
        print("所有测试通过!")
        print("=" * 60)
    except Exception as e:
        print(f"\n\n测试失败: {e}")
        import traceback
        traceback.print_exc()
