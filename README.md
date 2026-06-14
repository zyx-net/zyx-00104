# 设备校准证书接收与放行服务

基于 Flask 的本地 JSON API 服务，用于管理设备校准证书的接收、校验、审批和放行流程。

## 功能特性

- 支持 JSON/CSV 格式证书导入
- 完整的数据校验（设备编号、日期、有效期、量程、单位、偏差值）
- 自动化工作流程：录入 → 计量员复核 → 主管批准 → 放行/限用/停用
- 严格的错误处理：日期倒挂、设备不匹配、偏差超阈值、权限校验
- 完整的审计日志：操作者、备注、决策依据、版本记录
- 数据持久化：SQLite 数据库，确保服务重启后数据一致
- 导出功能：支持按设备或批次导出 JSON/CSV

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
flask init-db
```

或者直接运行应用，数据库会自动创建。

### 3. 启动服务

```bash
python app.py
```

服务将在 http://localhost:5000 运行。

## API 端点

### 健康检查

```bash
curl http://localhost:5000/api/health
```

### 设备管理

#### 创建设备
```bash
curl -X POST http://localhost:5000/api/equipment \
  -H "Content-Type: application/json" \
  -d @samples/equipment.json
```

#### 导入设备清单（批量）
```bash
curl -X POST http://localhost:5000/api/equipment \
  -H "Content-Type: application/json" \
  -d '[
    {
      "equipment_no": "EQ-2024-001",
      "equipment_name": "Digital Multimeter",
      "model_spec": "FLUKE 87V",
      "manufacturer": "Fluke Corporation",
      "range_min": 0,
      "range_max": 1000,
      "unit": "V",
      "tolerance": 0.05,
      "location": "Lab A"
    }
  ]'
```

#### 查看所有设备
```bash
curl http://localhost:5000/api/equipment
```

#### 查看单个设备
```bash
curl http://localhost:5000/api/equipment/1
```

### 证书导入

#### JSON 格式导入
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d @samples/certificates_valid.json
```

#### CSV 格式导入
```bash
curl -X POST http://localhost:5000/api/certificates/import/csv \
  -F "file=@samples/certificates.csv" \
  -F "operator=Zhang San" \
  -F "batch_id=BATCH-2024-001"
```

#### 单个证书导入
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "batch_id": "BATCH-2024-002",
    "data": [
      {
        "cert_no": "CERT-2024-001",
        "equipment_no": "EQ-2024-001",
        "calibration_date": "2024-06-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.02,
        "calibrator": "Zhang San"
      }
    ]
  }'
```

### 证书查询

#### 查看所有证书
```bash
curl http://localhost:5000/api/certificates
```

#### 按工作流状态筛选
```bash
curl "http://localhost:5000/api/certificates?workflow_status=draft"
```

#### 按设备筛选
```bash
curl "http://localhost:5000/api/certificates?equipment_id=1"
```

#### 按批次筛选
```bash
curl "http://localhost:5000/api/certificates?batch_id=BATCH-2024-001"
```

#### 查看单个证书
```bash
curl http://localhost:5000/api/certificates/1
```

### 工作流程操作

#### 1. 录入（Entry）
```bash
curl -X POST http://localhost:5000/api/certificates/1/enter \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator1",
    "notes": "Certificate data entered and verified"
  }'
```

#### 2. 计量员复核（Review）
```bash
curl -X POST http://localhost:5000/api/certificates/1/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Metrologist1",
    "notes": "Technical review completed",
    "decision_basis": "All parameters within specification"
  }'
```

#### 3. 主管批准（Approve）
```bash
curl -X POST http://localhost:5000/api/certificates/1/approve \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "notes": "Approved for release",
    "decision_basis": "Meets quality standards"
  }'
```

#### 4. 放行（Release）
```bash
curl -X POST http://localhost:5000/api/certificates/1/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor2",
    "notes": "Device cleared for use",
    "decision_basis": "All checks passed"
  }'
```

> **注意**：放行操作需要主管角色（supervisor）。录入员和计量员无权执行放行操作。

#### 限用（Limit）
```bash
curl -X POST http://localhost:5000/api/certificates/1/limit \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "notes": "Limited to specific range",
    "decision_basis": "Deviation in upper range"
  }'
```

#### 停用（Stop）
```bash
curl -X POST http://localhost:5000/api/certificates/1/stop \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "notes": "Device decommissioned",
    "decision_basis": "Failed accuracy requirements"
  }'
```

### 过期预警

#### 获取即将过期的证书
```bash
curl http://localhost:5000/api/certificates/expiry-warning
```

#### 自定义预警天数
```bash
curl "http://localhost:5000/api/certificates/expiry-warning?days=7"
```

响应示例：
```json
{
  "warning_days_used": 30,
  "count": 2,
  "certificates": [
    {
      "id": 1,
      "cert_no": "CERT-2024-001",
      "valid_until": "2024-06-20",
      "workflow_status": "released",
      ...
    }
  ]
}
```

### 过期自动流转

#### 触发过期证书自动处理
```bash
curl -X POST http://localhost:5000/api/certificates/expiry-process
```

响应示例：
```json
{
  "processed": 3,
  "limited": 1,
  "stopped": 2,
  "equipment_updated": 1,
  "details": [
    {
      "certificate_id": 1,
      "cert_no": "CERT-2024-001",
      "previous_status": "approved",
      "new_status": "limited",
      "valid_until": "2024-06-13"
    },
    {
      "certificate_id": 2,
      "cert_no": "CERT-2024-002",
      "previous_status": "approved",
      "new_status": "stopped",
      "valid_until": "2024-06-10"
    }
  ]
}
```

#### 过期流转规则
- **触发条件**：证书 `valid_until` < 当前日期，且状态为 `draft`/`entered`/`reviewed`/`approved`
- **状态判断**：
  - 偏差 ≤ 设备容忍度 → `limited`（限用）
  - 偏差 > 设备容忍度 → `stopped`（停用）
- **设备联动**：设备下所有证书都 `stopped` 时，设备状态自动更新为 `stopped`
- **审计日志**：所有流转记录操作人为 `SYSTEM_AUTO_EXPIRY`，便于与人工操作区分

### 证书搜索

#### 基础搜索（返回所有证书，分页）
```bash
curl "http://localhost:5000/api/certificates/search"
```

#### 按证书编号模糊搜索
```bash
curl "http://localhost:5000/api/certificates/search?cert_no=CERT-2024"
```

#### 按工作流状态筛选
```bash
curl "http://localhost:5000/api/certificates/search?workflow_status=released"
```

#### 按设备编号筛选
```bash
curl "http://localhost:5000/api/certificates/search?equipment_no=EQ-2024-001"
```

#### 按批次筛选
```bash
curl "http://localhost:5000/api/certificates/search?batch_id=BATCH-2024-001"
```

#### 按校准日期范围筛选
```bash
curl "http://localhost:5000/api/certificates/search?calibration_date_from=2024-01-01&calibration_date_to=2024-06-30"
```

#### 按操作人筛选（匹配录入/复核/批准/放行人）
```bash
curl "http://localhost:5000/api/certificates/search?operator=Zhang"
```

#### 组合条件搜索
```bash
curl "http://localhost:5000/api/certificates/search?workflow_status=released&equipment_no=EQ-2024&calibration_date_from=2024-01-01"
```

#### 分页参数
```bash
curl "http://localhost:5000/api/certificates/search?page=2&per_page=10"
```

#### 排序参数
```bash
# 按到期日升序（默认）
curl "http://localhost:5000/api/certificates/search?sort_by=valid_until&sort_order=asc"

# 按到期日降序
curl "http://localhost:5000/api/certificates/search?sort_by=valid_until&sort_order=desc"

# 按校准日期排序
curl "http://localhost:5000/api/certificates/search?sort_by=calibration_date&sort_order=desc"
```

#### 搜索响应示例
```json
{
  "items": [
    {
      "id": 1,
      "cert_no": "CERT-2024-001",
      "batch_id": "BATCH-2024-001",
      "equipment_id": 1,
      "equipment_no": "EQ-2024-001",
      "equipment_name": "Digital Multimeter",
      "calibration_date": "2024-06-01",
      "valid_until": "2025-06-01",
      "range_min": 0,
      "range_max": 1000,
      "unit": "V",
      "deviation": 0.02,
      "calibrator": "Zhang San",
      "workflow_status": "released",
      "entered_by": "Operator1",
      "reviewed_by": "Metrologist1",
      "approved_by": "Supervisor1",
      "released_by": "Supervisor2",
      "version": 4,
      "created_at": "2024-06-01T10:00:00",
      "updated_at": "2024-06-01T12:00:00"
    }
  ],
  "total": 25,
  "page": 1,
  "per_page": 20,
  "pages": 2,
  "has_next": true,
  "has_prev": false
}
```

#### 搜索特点
- **安全字段**：只返回安全字段，不暴露 `cert_file` 等敏感信息
- **分页越界**：页码超出范围时返回空列表，不报错
- **参数修正**：无效分页参数自动修正（负数页码→1，超大每页数→20）
- **模糊匹配**：证书编号、设备编号、批次号、操作人均支持模糊匹配

### 批次统计

#### 获取批次统计信息
```bash
curl http://localhost:5000/api/batches/stats
```

响应示例：
```json
{
  "BATCH-2024-001": {
    "total": 10,
    "draft": 2,
    "released": 5,
    "approved": 3
  },
  "BATCH-2024-002": {
    "total": 5,
    "released": 5
  }
}
```

### 配置管理

#### 获取过期预警天数配置
```bash
curl http://localhost:5000/api/config/expiry-warning-days
```

#### 设置过期预警天数
```bash
curl -X PUT http://localhost:5000/api/config/expiry-warning-days \
  -H "Content-Type: application/json" \
  -d '{"days": 60}'
```

#### 获取过期检测间隔配置
```bash
curl http://localhost:5000/api/config/expiry-check-interval
```

响应示例：
```json
{
  "expiry_check_interval_hours": 24,
  "last_check_time": "2026-06-13T10:00:00",
  "check_in_progress": false
}
```

#### 设置过期检测间隔
```bash
curl -X PUT http://localhost:5000/api/config/expiry-check-interval \
  -H "Content-Type: application/json" \
  -d '{"hours": 12}'
```

### 审计日志

#### 查看所有审计记录
```bash
curl http://localhost:5000/api/audit
```

#### 按证书筛选
```bash
curl "http://localhost:5000/api/audit?certificate_id=1"
```

#### 按操作者筛选
```bash
curl "http://localhost:5000/api/audit?operator=Metrologist1"
```

#### 按批次筛选
```bash
curl "http://localhost:5000/api/audit?batch_id=BATCH-2024-001"
```

#### 按操作类型筛选（包括权限拒绝）
```bash
curl "http://localhost:5000/api/audit?action=permission_denied"
```

### 数据导出

#### 按设备导出 JSON
```bash
curl "http://localhost:5000/api/export/equipment/1" > equipment_1_certs.json
```

#### 按设备导出 CSV
```bash
curl "http://localhost:5000/api/export/equipment/1?format=csv" > equipment_1_certs.csv
```

#### 按批次导出 JSON
```bash
curl "http://localhost:5000/api/export/batch/BATCH-2024-001" > batch_certs.json
```

#### 按批次导出 CSV
```bash
curl "http://localhost:5000/api/export/batch/BATCH-2024-001?format=csv" > batch_certs.csv
```

#### 导出所有证书
```bash
curl "http://localhost:5000/api/export/all" > all_certs.json
```

### 批量操作

#### 批量审批
```bash
curl -X POST http://localhost:5000/api/certificates/batch/approve \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "certificate_ids": [1, 2, 3],
    "notes": "Batch approval",
    "decision_basis": "All certificates meet quality standards"
  }'
```

响应示例（混合结果 - 部分成功部分失败）：
```json
{
  "total": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    {"certificate_id": 1, "cert_no": "CERT-001", "success": true, "workflow_status": "approved"},
    {"certificate_id": 2, "cert_no": "CERT-002", "success": true, "workflow_status": "approved"},
    {
      "certificate_id": 3,
      "cert_no": "CERT-003",
      "success": false,
      "errors": [{"error": "Invalid transition from draft to approved", "field": "workflow_status"}]
    }
  ]
}
```

#### 批量放行
```bash
curl -X POST http://localhost:5000/api/certificates/batch/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor2",
    "certificate_ids": [1, 2, 3],
    "notes": "Batch release",
    "decision_basis": "All checks passed"
  }'
```

响应示例（包含状态验证失败）：
```json
{
  "total": 3,
  "successful": 1,
  "failed": 2,
  "results": [
    {"certificate_id": 1, "cert_no": "CERT-001", "success": true, "workflow_status": "released"},
    {
      "certificate_id": 2,
      "cert_no": "CERT-002",
      "success": false,
      "errors": [{"error": "Invalid transition from draft to released", "field": "workflow_status"}]
    },
    {
      "certificate_id": 3,
      "cert_no": "CERT-003",
      "success": false,
      "errors": [{"error": "Invalid transition from reviewed to released", "field": "workflow_status"}]
    }
  ]
}
```

> **注意**：批量放行操作需要主管角色（supervisor），且证书必须处于 `approved` 状态。

#### 批量操作特点
- **非原子性**：每个证书独立处理，一个失败不影响其他
- **权限检查**：放行时检查操作人是否为录入人
- **状态验证**：只有处于审批通过(approved)状态的证书才能放行

### 操作撤销

#### 撤销最近工作流变更
```bash
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Admin1",
    "notes": "Revert due to incorrect approval"
  }'
```

响应示例：
```json
{
  "id": 1,
  "cert_no": "CERT-001",
  "workflow_status": "reviewed",
  "approved_by": null,
  "approved_at": null,
  "version": 5,
  ...
}
```

#### 撤销限制
- 只能撤销最近一次工作流变更
- 已撤销的变更不能再次撤销
- 撤销会恢复：
  - 证书工作流状态
  - 相关人员信息（approved_by, released_by 等）
  - 设备状态（如果是 release/limit/stop 操作）
- 撤销操作本身会记录审计日志

#### 重复撤销失败示例
```bash
# 第一次撤销成功
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{"operator": "Admin1", "notes": "First revert"}'

# 第二次撤销失败
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{"operator": "Admin1", "notes": "Second revert"}'

# 响应：
{
  "errors": [
    {"error": "No workflow change to revert"}
  ]
}
```

#### 撤销草稿状态失败示例
```bash
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{"operator": "Admin1", "notes": "Try to revert draft"}'

# 响应：
{
  "errors": [
    {"error": "No workflow change to revert"}
  ]
}
```

## 错误处理示例

### 1. 日期倒挂错误
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "data": [
      {
        "cert_no": "CERT-2024-ERROR-001",
        "equipment_no": "EQ-2024-001",
        "calibration_date": "2025-07-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.02
      }
    ]
  }'
```

响应：
```json
{
  "batch_id": "xxx",
  "total": 1,
  "successful": 0,
  "failed": 1,
  "errors": [
    {
      "index": 0,
      "cert_no": "CERT-2024-ERROR-001",
      "errors": [
        {
          "field": "valid_until",
          "error": "Valid until date must be after calibration date: 2025-06-01 <= 2025-07-01"
        }
      ]
    }
  ],
  "imported": []
}
```

### 2. 设备不匹配错误
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "data": [
      {
        "cert_no": "CERT-2024-ERROR-002",
        "equipment_no": "EQ-2024-999",
        "calibration_date": "2024-06-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.02
      }
    ]
  }'
```

响应：
```json
{
  "errors": [
    {
      "field": "equipment_no",
      "error": "Equipment EQ-2024-999 not found"
    }
  ]
}
```

### 3. 偏差超阈值错误
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "data": [
      {
        "cert_no": "CERT-2024-ERROR-003",
        "equipment_no": "EQ-2024-001",
        "calibration_date": "2024-06-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.1
      }
    ]
  }'
```

响应：
```json
{
  "errors": [
    {
      "field": "deviation",
      "error": "Deviation 0.1 exceeds tolerance 0.05"
    }
  ]
}
```

### 4. 录入员越权放行（权限拒绝）
```bash
curl -X POST http://localhost:5000/api/certificates/1/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator1"
  }'
```

响应：
```json
{
  "error": "Action 'release' requires role: 主管, but user has role: 录入员",
  "required_role": ["supervisor"],
  "operator_role": "operator",
  "action": "release",
  "resource_type": "certificate",
  "resource_id": 1
}
```

### 5. 录入员越权复核（权限拒绝）
```bash
curl -X POST http://localhost:5000/api/certificates/1/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator1",
    "decision_basis": "Try to review"
  }'
```

响应：
```json
{
  "error": "Action 'review' requires role: 计量员/主管, but user has role: 录入员",
  "required_role": ["metrologist", "supervisor"],
  "operator_role": "operator",
  "action": "review",
  "resource_type": "certificate",
  "resource_id": 1
}
```

### 6. 计量员越权放行（权限拒绝）
```bash
curl -X POST http://localhost:5000/api/certificates/1/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Metrologist1",
    "decision_basis": "Try to release"
  }'
```

响应：
```json
{
  "error": "Action 'release' requires role: 主管, but user has role: 计量员",
  "required_role": ["supervisor"],
  "operator_role": "metrologist",
  "action": "release",
  "resource_type": "certificate",
  "resource_id": 1
}
```

## 工作流程状态

```
DRAFT → ENTERED → REVIEWED → APPROVED → RELEASED/LIMITED/STOPPED
```

- **DRAFT**: 草稿状态，证书刚导入
- **ENTERED**: 已录入，数据录入员确认
- **REVIEWED**: 已复核，计量员审核通过
- **APPROVED**: 已批准，主管审批通过
- **RELEASED**: 已放行，设备可正常使用
- **LIMITED**: 限用，设备在限制条件下使用
- **STOPPED**: 停用，设备不可使用

## 数据一致性保证

1. **事务处理**: 所有导入操作使用数据库事务，失败时自动回滚
2. **原子性**: 批量导入要么全部成功，要么全部失败，不留半条记录
3. **持久化**: 使用 SQLite 数据库，服务重启后数据不丢失
4. **幂等性**: 相同批次号再次导入会检测重复证书号，防止重复导入
5. **版本控制**: 每次状态变更都会增加版本号，保留历史记录

## 审计日志字段

- `timestamp`: 操作时间
- `operator`: 操作者
- `action`: 操作类型（import, enter, review, approve, release, limit, stop, revert, permission_denied）
- `resource_type`: 资源类型（equipment, certificate, system）
- `resource_id`: 资源ID
- `notes`: 备注
- `decision_basis`: 决策依据
- `version`: 版本号
- `previous_state`: 前一个状态
- `new_state`: 新状态
- `reverted`: 是否已被撤销
- `reverted_by`: 撤销操作人
- `reverted_at`: 撤销时间
- `revert_log_id`: 关联的撤销日志ID
- `denied_reason`: 权限拒绝原因（仅 permission_denied 事件）

## 角色权限说明

系统支持三种角色，各角色权限如下：

| 角色 | 录入员 (operator) | 计量员 (metrologist) | 主管 (supervisor) |
|------|------------------|---------------------|-------------------|
| 导入证书 | ✓ | ✓ | ✓ |
| 录入证书 | ✓ | ✓ | ✓ |
| 复核证书 | ✗ | ✓ | ✓ |
| 批准证书 | ✗ | ✗ | ✓ |
| 放行证书 | ✗ | ✗ | ✓ |
| 限用证书 | ✗ | ✗ | ✓ |
| 停用证书 | ✗ | ✗ | ✓ |
| 撤销操作 | ✗ | ✗ | ✓ |

### 权限验证规则

1. **角色不匹配时返回 403**：当用户执行超出其角色权限的操作时，系统返回 403 Forbidden
2. **权限拒绝事件记录**：所有权限拒绝事件都会被记录到审计日志，方便排查
3. **录入员不能放行自己的单**：即使是主管角色，也受此规则限制

### 权限拒绝响应示例

```json
{
  "error": "Action 'approve' requires role: 主管, but user has role: 录入员",
  "required_role": ["supervisor"],
  "operator_role": "operator",
  "action": "approve",
  "resource_type": "certificate",
  "resource_id": 123
}
```

## 用户管理

### 创建用户

```bash
curl -X POST http://localhost:5000/api/users \
  -H "Content-Type: application/json" \
  -d '{
    "username": "Zhang San",
    "role": "operator"
  }'
```

有效角色值：`operator`、`metrologist`、`supervisor`

### 获取用户列表

```bash
curl http://localhost:5000/api/users
```

### 获取单个用户

```bash
curl http://localhost:5000/api/users/Zhang%20San
```

### 更新用户角色

```bash
curl -X PUT http://localhost:5000/api/users/Zhang%20San/role \
  -H "Content-Type: application/json" \
  -d '{"role": "supervisor"}'
```

## 定时任务调度器

### 调度器状态

```bash
curl http://localhost:5000/api/scheduler/status
```

响应示例：
```json
{
  "running": true,
  "last_check_time": "2026-06-13T10:00:00",
  "check_interval_hours": 24,
  "check_in_progress": false
}
```

### 启动调度器

```bash
curl -X POST http://localhost:5000/api/scheduler/start
```

### 停止调度器

```bash
curl -X POST http://localhost:5000/api/scheduler/stop
```

### 调度器特性

1. **自动启动**：服务启动时自动启动调度器
2. **平滑停止**：服务停止时自动停止调度器
3. **持久化配置**：调度器配置保存在 `config.json` 中，重启后恢复
4. **冲突保护**：如果检测任务正在运行，手动触发会返回 409 Conflict

### 配置修改与重启验证

修改检测频率后重启服务，配置会持久化保存：

```bash
# 1. 修改检测频率为 12 小时
curl -X PUT http://localhost:5000/api/config/expiry-check-interval \
  -H "Content-Type: application/json" \
  -d '{"hours": 12}'

# 响应：
{
  "expiry_check_interval_hours": 12,
  "message": "Expiry check interval updated to 12 hours"
}

# 2. 查看配置文件确认已保存
cat config.json
# {
#   "expiry_warning_days": 60,
#   "expiry_check_interval_hours": 12,
#   "expiry_check_in_progress": false,
#   "last_expiry_check_time": "2026-06-14T10:00:00"
# }

# 3. 重启服务
# Ctrl+C 停止服务，然后重新启动
python app.py

# 4. 验证配置未丢失
curl http://localhost:5000/api/config/expiry-check-interval
# 响应：
{
  "expiry_check_interval_hours": 12,
  "last_check_time": "2026-06-14T10:00:00",
  "check_in_progress": false
}

# 5. 验证调度器按新频率运行
curl http://localhost:5000/api/scheduler/status
# 响应：
{
  "running": true,
  "check_interval_hours": 12,
  "last_check_time": "2026-06-14T10:00:00",
  "check_in_progress": false
}
```

### 并发冲突保护

当定时检测任务正在执行时，如果有人手动调用过期处理接口，系统会返回 409 Conflict：

```bash
# 场景：定时任务正在执行过期检测
# 此时手动触发过期处理

curl -X POST http://localhost:5000/api/certificates/expiry-process

# 响应（409 Conflict）：
{
  "error": "Another expiry check is already in progress",
  "conflict": true
}
```

**冲突保护机制说明**：
- 系统使用 `expiry_check_in_progress` 标志位防止并发执行
- 定时任务开始时设置标志位为 `true`，结束时设置为 `false`
- 手动触发时检查标志位，如果为 `true` 则返回 409
- 这确保了过期处理不会重复执行，避免数据冲突

## 目录结构

```
.
├── app.py                  # 主应用文件
├── models.py               # 数据模型
├── services.py             # 业务逻辑层
├── validators.py           # 数据校验
├── test_app.py            # 基础功能测试
├── test_scheduler.py      # 调度器和权限测试
├── requirements.txt        # 依赖列表
├── calibration.db          # SQLite 数据库（自动生成）
├── samples/
│   ├── equipment.json      # 设备清单样例
│   ├── certificates_valid.json    # 有效证书样例
│   ├── certificates_errors.json  # 错误证书样例
│   └── certificates.csv    # CSV 格式证书样例
└── README.md              # 本文档
```

## 测试建议

1. 先导入设备清单
2. 导入有效证书，确认成功
3. 导入错误证书，确认校验失败
4. 完整执行工作流程：录入→复核→批准→放行
5. 查看审计日志，确认记录完整
6. 导出数据，验证格式正确

## 校准任务调度模块

### 功能概述

校准任务调度模块用于管理校准任务的创建、分派、跟踪和完成，支持以下特性：

- **任务类型**：周期循环任务、临时加急任务、批量派单任务
- **状态流转**：待派发 → 已接单 → 执行中 → 已完成 → 异常关闭
- **冲突检测**：同设备存在未完成任务时创建新任务会提示冲突
- **强制覆盖**：允许主管强制覆盖冲突任务，操作记录审计日志且不可撤销
- **审计日志**：每次状态切换都记录完整审计日志
- **热加载**：调度策略配置支持文件监控热加载

### API 端点

#### 创建校准任务

```bash
curl -X POST http://localhost:5000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "equipment_id": 1,
    "task_type": "periodic",
    "planned_date": "2026-07-01",
    "calibrator": "Zhang San",
    "priority": 5,
    "period_days": 365
  }'
```

#### 批量创建任务

```bash
curl -X POST http://localhost:5000/api/tasks/batch \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "equipment_ids": [1, 2, 3],
    "task_type": "batch"
  }'
```

#### 查询任务列表

```bash
curl "http://localhost:5000/api/tasks?status=pending&page=1&per_page=20"
```

#### 接单、开始、完成任务

```bash
curl -X POST http://localhost:5000/api/tasks/1/accept -d '{"operator": "Zhang San"}'
curl -X POST http://localhost:5000/api/tasks/1/start -d '{"operator": "Zhang San"}'
curl -X POST http://localhost:5000/api/tasks/1/complete -d '{"operator": "Supervisor1", "execution_notes": "Done"}'
```

#### 调度配置

```json
{
  "scheduler": {
    "default_priority": 0,
    "urgent_priority": 10,
    "auto_create_next_periodic": true,
    "allow_force_override": true
  }
}
```

### 权限控制

| 操作 | 录入员 | 计量员 | 主管 |
|------|--------|--------|------|
| 创建任务 | ✗ | ✗ | ✓ |
| 接单/开始 | ✓ | ✓ | ✓ |
| 完成/关闭 | ✗ | ✗ | ✓ |
