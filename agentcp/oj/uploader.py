from __future__ import annotations
import requests
import re
import html as html_lib
import os
import time
import zipfile
import mimetypes
from urllib.parse import quote, urljoin

from ..domain.models import OrganizationOption

class OJUploader:
    def __init__(self, url, username, password):
        self.base_url = url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        })
        self.last_created_problem_code = ""

    def _make_soup(self, html):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, 'html.parser')

    def _collect_form_data(self, soup):
        data = {}
        for tag in soup.find_all(['input', 'textarea', 'select']):
            name = tag.get('name')
            if not name or name == 'submit':
                continue

            if tag.name == 'input' and tag.get('type') in {'file', 'submit', 'button', 'image', 'reset'}:
                continue

            if tag.name == 'input' and tag.get('type') == 'checkbox':
                if tag.has_attr('checked'):
                    data[name] = 'on'
            elif tag.name == 'select':
                selected = tag.find('option', selected=True)
                if selected and selected.get('value') is not None:
                    data[name] = selected.get('value')
                else:
                    first = tag.find('option')
                    if first and first.get('value') is not None:
                        data[name] = first.get('value')
            else:
                value = tag.get('value', '')
                data[name] = value if value is not None else (tag.string or '')
        return data

    def _extract_field_value_from_html(self, html, field_name):
        pattern_name = re.escape(field_name)

        checkbox_checked = re.search(
            rf'<input[^>]*name=["\']{pattern_name}["\'][^>]*type=["\']checkbox["\'][^>]*checked',
            html,
            re.I | re.S,
        )
        if checkbox_checked:
            return 'on'

        input_match = re.search(
            rf'<input[^>]*name=["\']{pattern_name}["\'][^>]*value=["\']([^"\']*)["\']',
            html,
            re.I | re.S,
        )
        if input_match:
            return html_lib.unescape(input_match.group(1))

        textarea_match = re.search(
            rf'<textarea[^>]*name=["\']{pattern_name}["\'][^>]*>(.*?)</textarea>',
            html,
            re.I | re.S,
        )
        if textarea_match:
            return html_lib.unescape(re.sub(r'\s+', ' ', textarea_match.group(1)).strip())

        select_match = re.search(
            rf'<select[^>]*name=["\']{pattern_name}["\'][^>]*>(.*?)</select>',
            html,
            re.I | re.S,
        )
        if select_match:
            inner = select_match.group(1)
            option_match = re.search(
                r'<option[^>]*value=["\']([^"\']*)["\'][^>]*selected',
                inner,
                re.I | re.S,
            )
            if not option_match:
                option_match = re.search(
                    r'<option[^>]*selected[^>]*value=["\']([^"\']*)["\']',
                    inner,
                    re.I | re.S,
                )
            if not option_match:
                option_match = re.search(
                    r'<option[^>]*value=["\']([^"\']*)["\']',
                    inner,
                    re.I | re.S,
                )
            if option_match:
                return html_lib.unescape(option_match.group(1))

        return None

    def _extract_zip_valid_files(self, zip_path):
        valid_files = []
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    name = info.filename.replace('\\', '/').strip()
                    if not name or name.endswith('/'):
                        continue
                    base = os.path.basename(name)
                    if name.startswith('__MACOSX/') or base.startswith('._') or base == '.DS_Store':
                        continue
                    valid_files.append(name)
        except Exception:
            return []

        def natural_key(value):
            parts = re.split(r'(\d+)', value.lower())
            return [int(p) if p.isdigit() else p for p in parts]

        return sorted(valid_files, key=natural_key)

    def _build_case_form_submission(self, form, html, valid_files):
        data = self._collect_form_data(form)

        def natural_key(value):
            parts = re.split(r'(\d+)', value.lower())
            return [int(p) if p.isdigit() else p for p in parts]

        in_patterns = ['.in', '.inp']
        out_patterns = ['.out', '.ans', '.ok', '.a']
        in_files = sorted([f for f in valid_files if any(f.lower().endswith(p) for p in in_patterns)], key=natural_key)
        out_files = sorted([f for f in valid_files if any(f.lower().endswith(p) for p in out_patterns)], key=natural_key)
        pair_count = min(len(in_files), len(out_files))

        existing_indices = sorted(set(int(idx) for idx in re.findall(r'name=["\']cases-(\d+)-id["\']', html, re.I)))
        existing_count = len(existing_indices)
        total_forms = max(existing_count, pair_count)

        initial_forms = data.get('cases-INITIAL_FORMS', str(existing_count))
        min_forms = data.get('cases-MIN_NUM_FORMS', '0')
        max_forms = data.get('cases-MAX_NUM_FORMS', '1000')
        data['cases-TOTAL_FORMS'] = str(total_forms)
        data['cases-INITIAL_FORMS'] = str(initial_forms)
        data['cases-MIN_NUM_FORMS'] = str(min_forms)
        data['cases-MAX_NUM_FORMS'] = str(max_forms)

        existing_fields = ['id', 'order', 'type', 'input_file', 'output_file', 'points', 'is_pretest', 'DELETE']
        for i in range(existing_count):
            prefix = f'cases-{i}-'
            for field in existing_fields:
                value = self._extract_field_value_from_html(html, f'{prefix}{field}')
                if value is not None:
                    data[f'{prefix}{field}'] = value

        for i in range(total_forms):
            prefix = f'cases-{i}-'
            if i < pair_count:
                data[f'{prefix}input_file'] = in_files[i]
                data[f'{prefix}output_file'] = out_files[i]
                data[f'{prefix}points'] = '1'
                data[f'{prefix}order'] = str(i + 1)
                data[f'{prefix}type'] = 'C'
                data[f'{prefix}is_pretest'] = data.get(f'{prefix}is_pretest', '')
                data.pop(f'{prefix}DELETE', None)
            elif i < existing_count:
                data[f'{prefix}DELETE'] = 'on'
            else:
                data[f'{prefix}id'] = ''
                data[f'{prefix}order'] = str(i + 1)
                data[f'{prefix}type'] = 'C'
                data[f'{prefix}input_file'] = in_files[i] if i < len(in_files) else ''
                data[f'{prefix}output_file'] = out_files[i] if i < len(out_files) else ''
                data[f'{prefix}points'] = '1'
                data[f'{prefix}is_pretest'] = ''
                data[f'{prefix}DELETE'] = ''

        return data, pair_count, existing_count

    def _post_problem_form(self, url, data, statement_path=None, referer=None):
        files = {}
        if statement_path and os.path.exists(statement_path):
            with open(statement_path, 'rb') as f:
                files['statement_file'] = (
                    os.path.basename(statement_path),
                    f.read(),
                    self._statement_file_mimetype(statement_path),
                )
        return self.session.post(url, data=data, files=files, headers={'Referer': referer or url}, allow_redirects=True)

    def _statement_file_mimetype(self, statement_path):
        mime, _ = mimetypes.guess_type(statement_path or "")
        return mime or "application/octet-stream"

    def _form_field_names(self, soup):
        names = set()
        for tag in soup.find_all(['input', 'textarea', 'select']):
            name = tag.get('name')
            if name:
                names.add(name)
        return names

    def _set_organization_payload_field(self, soup, data, organization_id=None):
        organization_id = (organization_id or "").strip()
        if not organization_id:
            return False
        field_names = self._form_field_names(soup)
        for field_name in ("organization", "organization_id", "org", "org_id", "owner", "authors"):
            if field_name in field_names:
                data[field_name] = organization_id
                return True
        return False

    def _has_organization_payload_field(self, soup):
        field_names = self._form_field_names(soup)
        return any(field_name in field_names for field_name in ("organization", "organization_id", "org", "org_id", "owner", "authors"))

    def _problem_code_with_form_prefix(self, form_code_value, code):
        prefix = (form_code_value or "").strip()
        code = (code or "").strip()
        if prefix and prefix.endswith("_") and not code.startswith(prefix):
            return f"{prefix}{code}"
        return code

    def _build_problem_payload(self, soup, code, name, summary, description, time_limit, memory_limit, points, is_public, submit_label, organization_id=None):
        data = self._collect_form_data(soup)
        problem_code = code
        if organization_id:
            problem_code = self._problem_code_with_form_prefix(data.get("code", ""), code)
        data.update({
            'code': problem_code,
            'name': name,
            'time_limit': str(time_limit),
            'memory_limit': str(memory_limit),
            'points': str(points),
            'is_public': 'on' if is_public else '',
            'partial': 'on',
            'description': description,
            'body': description,
            'submit': submit_label,
        })
        if 'summary' in str(soup):
            data['summary'] = summary

        def pick_option(field_name, is_multiple=False, keyword="chưa phân loại"):
            sel = soup.find('select', {'name': field_name})
            if not sel:
                return
            target_opt = None
            for opt in sel.find_all('option'):
                if keyword.lower() in opt.text.lower() or opt.get('value') == "1":
                    target_opt = opt
                    break
            if not target_opt:
                for opt in sel.find_all('option'):
                    if opt.get('value'):
                        target_opt = opt
                        break
            if target_opt:
                val = target_opt.get('value')
                data[field_name] = [val] if is_multiple else val

        pick_option('types', is_multiple=True, keyword="chưa phân loại")
        pick_option('group', is_multiple=False, keyword="chưa phân loại")
        pick_option('submission_source_visibility_mode', is_multiple=False, keyword="follow")
        pick_option('testcase_visibility_mode', is_multiple=False, keyword="chỉ tác giả")
        self._set_organization_payload_field(soup, data, organization_id=organization_id)
        return data

    def _select_first_option_value(self, soup, field_name, fallback="", preferred_value=None):
        sel = soup.find('select', {'name': field_name})
        if not sel:
            return fallback

        if preferred_value is not None:
            for opt in sel.find_all('option'):
                if opt.get('value') == preferred_value:
                    return preferred_value

        selected = sel.find('option', selected=True)
        if selected and selected.get('value') is not None:
            value = selected.get('value')
            if value != "":
                return value

        first = sel.find('option')
        if first and first.get('value') is not None:
            value = first.get('value')
            if value != "":
                return value

        return fallback

    def _extract_form_error_summary(self, html):
        errors = []
        try:
            soup = self._make_soup(html)
            for ul in soup.find_all(lambda tag: tag.name == "ul" and tag.get("class") and any(cls.startswith("errorlist") for cls in tag.get("class", []))):
                messages = []
                for li in ul.find_all("li"):
                    msg = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
                    if msg:
                        messages.append(msg)
                if not messages:
                    msg = re.sub(r"\s+", " ", ul.get_text(" ", strip=True)).strip()
                    if msg:
                        messages.append(msg)
                for message in messages:
                    if message not in errors:
                        errors.append(message)
        except Exception:
            pass

        if not errors:
            pattern = re.compile(r'<ul[^>]*class=["\"][^"\"]*errorlist[^"\"]*["\"][^>]*>(.*?)</ul>', re.I | re.S)
            for match in pattern.finditer(html):
                message = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', match.group(1))).strip()
                if message and message not in errors:
                    errors.append(message)
        return errors

    def _dump_upload_zip_debug(self, data, file_field, zip_path, response_text=None):
        try:
            with open("upload_zip_request_debug.txt", "w", encoding="utf-8") as f:
                f.write(f"zip_path={zip_path}\n")
                f.write(f"file_field={file_field}\n")
                for key in sorted(data.keys()):
                    value = data.get(key, "")
                    f.write(f"{key}={value!r}\n")
            if response_text is not None:
                with open("upload_zip_response_debug.html", "w", encoding="utf-8") as f:
                    f.write(response_text)
        except Exception:
            pass

    def _organization_id_from_url(self, href):
        match = re.search(r"/organizations?/([^/?#]+)/?", href or "", re.I)
        if not match:
            return ""
        value = match.group(1).strip()
        if value.lower() in {"create", "new", "add"}:
            return ""
        return value

    def _absolute_url(self, href):
        return urljoin(self.base_url + "/", href or "")

    def _find_problem_form(self, soup):
        for form in soup.find_all("form"):
            if form.find(["input", "textarea", "select"], {"name": "code"}):
                return form
        if soup.find(["input", "textarea", "select"], {"name": "code"}):
            return soup
        return None

    def _form_action_url(self, form, current_url):
        action = ""
        try:
            action = form.get("action") or ""
        except Exception:
            action = ""
        return urljoin(current_url, action) if action else current_url

    def _discover_organizations_from_html(self, html):
        soup = self._make_soup(html)
        options = {}
        for link in soup.find_all("a"):
            href = link.get("href") or ""
            org_id = self._organization_id_from_url(href)
            if not org_id:
                continue
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            is_create = bool(re.search(r"(problem|problems).*(create|add)|(create|add).*(problem|problems)", href, re.I))
            existing = options.get(org_id) or OrganizationOption(id=org_id, name=org_id)
            if text and not is_create and existing.name == org_id:
                existing.name = text
            if is_create:
                existing.create_url = self._absolute_url(href)
            options[org_id] = existing
        return list(options.values())

    def discover_organizations(self):
        pages = [
            f"{self.base_url}/organizations/",
            f"{self.base_url}/organization/",
            f"{self.base_url}/accounts/profile/",
            f"{self.base_url}/profile/",
        ]
        discovered = {}
        for url in pages:
            try:
                response = self.session.get(url)
            except Exception:
                continue
            if getattr(response, "status_code", 200) not in (200, 302):
                continue
            for option in self._discover_organizations_from_html(getattr(response, "text", "") or ""):
                current = discovered.get(option.id)
                if current is None:
                    discovered[option.id] = option
                elif option.create_url and not current.create_url:
                    current.create_url = option.create_url
        return sorted(discovered.values(), key=lambda item: item.name.lower())

    def _organization_create_url_candidates(self, organization_id, create_url=None):
        seen = set()
        candidates = []
        quoted_id = quote(organization_id or "", safe="")
        for url in (
            f"{self.base_url}/organization/{organization_id}/problem-create",
            create_url,
            f"{self.base_url}/organization/{organization_id}/problems/create",
            f"{self.base_url}/problems/create?organization={quoted_id}",
            f"{self.base_url}/organization/{organization_id}/problem/add/",
            f"{self.base_url}/organizations/{organization_id}/problems/create",
        ):
            if not url:
                continue
            absolute = self._absolute_url(url)
            if absolute in seen:
                continue
            seen.add(absolute)
            candidates.append(absolute)
        return candidates

    def login(self):
        """Đăng nhập vào hệ thống OJ và kiểm tra tính xác thực."""
        login_url = f"{self.base_url}/accounts/login/"
        try:
            r_get = self.session.get(login_url)
            csrf = self._get_csrf(r_get.text)
            
            r_post = self.session.post(login_url, data={
                'username': self.username,
                'password': self.password,
                'csrfmiddlewaretoken': csrf
            }, headers={'Referer': login_url}, allow_redirects=True)
            
            if "Logout" in r_post.text or "/accounts/logout/" in r_post.text:
                return True
            
            print(f"DEBUG: Login failed for user {self.username}. URL: {r_post.url}")
            return False
        except Exception as e:
            print(f"Login Exception: {str(e)}")
            return False

    def _get_csrf(self, html):
        """Trích xuất CSRF Token từ HTML."""
        match = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\'](.*?)["\']', html)
        return match.group(1) if match else self.session.cookies.get('csrftoken', '')

    def check_problem_exists(self, problem_code):
        """Kiểm tra xem mã bài đã tồn tại trên OJ chưa."""
        url = f"{self.base_url}/problem/{problem_code}/"
        try:
            r = self.session.get(url)
            return r.status_code == 200
        except Exception:
            return False

    def _fill_problem_form(self, soup, code, name, summary, description, time_limit, memory_limit, points, is_public, organization_id=None):
        """Hàm nội bộ để điền dữ liệu vào form, dùng chung cho Create và Edit."""
        title_text = getattr(getattr(soup, 'title', None), 'text', '').lower()
        submit_label = 'Tạo' if 'create' in title_text else 'Lưu'
        return self._build_problem_payload(soup, code, name, summary, description, time_limit, memory_limit, points, is_public, submit_label, organization_id=organization_id)

    def create_problem(self, code, name, summary, description, time=1.0, memory=262144, points=100, is_public=True, statement_path=None, organization_id=None, require_organization_field=False):
        """Khởi tạo bài toán mới trên OJ."""
        self.last_created_problem_code = ""
        add_url = f"{self.base_url}/problems/create"
        try:
            r_get = self.session.get(add_url)
            if r_get.status_code != 200:
                add_url = f"{self.base_url}/problem/add/"
                r_get = self.session.get(add_url)
            
            soup = self._make_soup(r_get.text)
            form = self._find_problem_form(soup)
            if form is None:
                return False, "Không tìm thấy form trên trang tạo bài."
            if require_organization_field and not self._has_organization_payload_field(form):
                return False, "Root create form does not expose an organization field."
            data = self._fill_problem_form(form, code, name, summary, description, time, memory, points, is_public, organization_id=organization_id)
            if not data:
                return False, "Không tìm thấy form trên trang tạo bài."

            post_url = self._form_action_url(form, add_url)
            r_post = self._post_problem_form(post_url, data, statement_path=statement_path, referer=add_url)
            submitted_code = data.get("code", code)
            if f"/problem/{submitted_code}" in r_post.url:
                self.last_created_problem_code = submitted_code
                return True, "Tạo bài mới thành công."
            return False, "Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại thủ công."
        except Exception as e:
            return False, f"Ngoại lệ: {str(e)}"

    def create_problem_in_organization(
        self,
        organization_id,
        code,
        name,
        summary,
        description,
        time=1.0,
        memory=262144,
        points=100,
        is_public=True,
        statement_path=None,
        create_url=None,
    ):
        organization_id = (organization_id or "").strip()
        if not organization_id and not create_url:
            return False, "Missing organization target."

        self.last_created_problem_code = ""
        last_message = ""
        for add_url in self._organization_create_url_candidates(organization_id, create_url=create_url):
            try:
                r_get = self.session.get(add_url)
                if getattr(r_get, "status_code", 200) != 200:
                    last_message = f"Cannot access organization create page (Status {r_get.status_code})"
                    continue
                soup = self._make_soup(r_get.text)
                form = self._find_problem_form(soup)
                if form is None:
                    last_message = "Could not find organization create form."
                    continue
                data = self._fill_problem_form(
                    form,
                    code,
                    name,
                    summary,
                    description,
                    time,
                    memory,
                    points,
                    is_public,
                    organization_id=organization_id,
                )
                if not data:
                    last_message = "Could not find organization create form."
                    continue
                post_url = self._form_action_url(form, add_url)
                r_post = self._post_problem_form(post_url, data, statement_path=statement_path, referer=add_url)
                submitted_code = data.get("code", code)
                if f"/problem/{submitted_code}" in r_post.url:
                    self.last_created_problem_code = submitted_code
                    return True, "Created problem in organization successfully."
                if "errorlist" in (r_post.text or ""):
                    errors = self._extract_form_error_summary(r_post.text)
                    return False, "; ".join(errors) if errors else "Organization form data is invalid."
                else:
                    return False, f"Organization create failed at {add_url}."
            except Exception as e:
                last_message = str(e)

        ok, msg = self.create_problem(
            code,
            name,
            summary,
            description,
            time=time,
            memory=memory,
            points=points,
            is_public=is_public,
            statement_path=statement_path,
            organization_id=organization_id,
            require_organization_field=True,
        )
        if ok:
            return ok, "Created problem with organization form field successfully."
        return False, last_message or msg

    def edit_problem(self, code, title, summary, content, time=1.0, memory=262144, points=100, is_public=False, clear_statement=False, statement_path=None):
        """Cập nhật thông tin đề bài cho bài đã tồn tại."""
        url = f"{self.base_url}/problem/{code}/edit"
        try:
            r_get = self.session.get(url)
            if r_get.status_code != 200:
                return False, f"Không thể truy cập trang chỉnh sửa (Status {r_get.status_code})"
                
            soup = self._make_soup(r_get.text)
            csrf = self._get_csrf(r_get.text)
            data = self._collect_form_data(soup)
            data.update({
                'csrfmiddlewaretoken': csrf,
                'title': title,
                'code': code,
                'description': content,
                'summary': summary,
                'time_limit': str(time),
                'memory_limit': str(memory),
                'submit': 'Save',
            })

            # Xử lý logic checkbox Is Public
            if is_public:
                data['is_public'] = 'on'
            else:
                data.pop('is_public', None)  # Xóa khỏi data nếu không public

            # Xử lý logic Clear Statement
            if clear_statement:
                data['statement_file-clear'] = 'on'
            else:
                data.pop('statement_file-clear', None)

            r_post = self._post_problem_form(url, data, statement_path=statement_path)
            if r_post.status_code == 200:
                if code in r_post.url and "errorlist" not in r_post.text:
                    return True, "Đã cập nhật đề bài thành công."
                if "errorlist" in r_post.text:
                    return False, "Dữ liệu form không hợp lệ (kiểm tra các ràng buộc)."
            
            return False, f"Lỗi server: Status {r_post.status_code}"
            
        except Exception as e:
            return False, f"Exception Edit: {str(e)}"

    def upload_zip(self, problem_code, zip_path, log_callback=None):
        """Tải lên ZIP testcase, sửa lỗi kiểm tra form cho bài đã có sẵn."""
        url = f"{self.base_url}/problem/{problem_code}/test_data"
        try:
            if log_callback:
                log_callback("    -> GET trang test data...")
            r_get = self.session.get(url)
            html = r_get.text or ""
            soup = self._make_soup(html)
            csrf = self._get_csrf(html)

            form = soup.find('form')
            if not form:
                return False, "Không tìm thấy form upload ZIP."

            file_field = 'problem-data-zipfile'
            m_file = re.search(r'<input[^>]*type=["\']file["\'][^>]*name=["\']([^"\']+)["\']', html, re.I | re.S)
            if m_file:
                file_field = m_file.group(1)

            valid_files = self._extract_zip_valid_files(zip_path)
            data, total_cases, existing_count = self._build_case_form_submission(form, html, valid_files)
            if not total_cases:
                return False, "ZIP không chứa cặp testcase hợp lệ (.in/.out, .inp/.out, .in/.ans, ...)."

            data.update({
                'csrfmiddlewaretoken': csrf,
                'submit': 'Apply!',
                'problem-data-grader': self._select_first_option_value(soup, 'problem-data-grader', 'standard', preferred_value='standard'),
                'problem-data-checker': self._select_first_option_value(soup, 'problem-data-checker', 'standard', preferred_value='standard'),
                'problem-data-checker_type': self._select_first_option_value(soup, 'problem-data-checker_type', 'default', preferred_value='default'),
                'problem-data-io_method': self._select_first_option_value(soup, 'problem-data-io_method', 'standard', preferred_value='standard'),
                'problem-data-io_input_file': '',
                'problem-data-io_output_file': '',
            })

            if log_callback:
                log_callback(
                    "    -> POST upload ZIP: "
                    f"file={os.path.basename(zip_path)}, cases={total_cases}, existing={existing_count}"
                )

            with open(zip_path, 'rb') as f:
                zip_bytes = f.read()

            files = {file_field: (os.path.basename(zip_path), zip_bytes, 'application/zip')}

            r_post = None
            last_exc = None
            for attempt in range(1, 4):
                post_session = None
                try:
                    post_session = requests.Session()
                    post_session.headers.update(self.session.headers)
                    post_session.cookies.update(self.session.cookies)
                    headers = {'Referer': url, 'Connection': 'close'}
                    r_post = post_session.post(url, data=data, files=files, headers=headers, timeout=120)
                    self.session.cookies.update(post_session.cookies)
                    post_session.close()
                    break
                except requests.exceptions.RequestException as exc:
                    last_exc = exc
                    if post_session is not None:
                        post_session.close()
                    exc_text = str(exc)
                    transient = (
                        'SSLWantWriteError' in exc_text or
                        'SSLWantReadError' in exc_text or
                        'Connection aborted' in exc_text or
                        'EOF occurred in violation of protocol' in exc_text
                    )
                    if transient and attempt < 3:
                        if log_callback:
                            log_callback(f"    -> ZIP retry {attempt}/3 do lỗi tạm thời: {exc}")
                        time.sleep(1.5 * attempt)
                        continue
                    raise
                finally:
                    if post_session is not None:
                        post_session.close()

            if log_callback:
                log_callback(f"    -> ZIP response: status={r_post.status_code}, url={r_post.url}")

            errors = self._extract_form_error_summary(r_post.text)
            if errors:
                with open("upload_error_debug.html", "w", encoding="utf-8") as f:
                    f.write(r_post.text)
                self._dump_upload_zip_debug(data, file_field, zip_path, response_text=r_post.text)
                if log_callback:
                    for item in errors[:8]:
                        log_callback(f"    -> ZIP error: {item}")
                    log_callback("    -> ZIP invalid; detailed HTML saved to upload_error_debug.html")
                return False, "Upload ZIP không hợp lệ: " + " | ".join(errors[:3])

            if r_post.status_code in [200, 302]:
                return True, "Upload ZIP thành công."
            return False, f"Lỗi server: Status {r_post.status_code}"
        except Exception as e:
            print(f"Upload ZIP Exception: {e}")
            return False, f"Upload ZIP Exception: {e}"

    def apply_test_data(self, problem_code, log_callback=None):
        """Ghép cặp và lưu cấu hình test case (Apply!) với cơ chế đợi giải nén (Polling)."""
        url = f"{self.base_url}/problem/{problem_code}/test_data"
        max_retries = 30  # 30 * 2 = 60 giây
        
        # Khởi tạo giá trị mặc định để tránh lỗi UnboundLocalError
        valid_files = []
        total_cases = 0 
        
        try:
            for i in range(max_retries):
                if log_callback:
                    log_callback(f"    -> Đang đợi máy chủ giải nén... (lần {i+1}/{max_retries})")
                time.sleep(2)
                
                r_page = self.session.get(url)
                valid_files = self._extract_valid_files(r_page.text)
                
                if valid_files:
                    soup = self._make_soup(r_page.text)
                    form = soup.find('form')
                    if not form:
                        continue
                    cases_data, total_cases, existing_count = self._build_case_form_submission(form, r_page.text, valid_files)
                    if total_cases > 0:
                        break  # Hoàn tất, thoát vòng lặp
                
            if not valid_files or total_cases == 0:
                with open("debug_test_data.html", "w", encoding="utf-8") as d:
                    d.write(r_page.text)
                return False, f"Không tìm thấy file hợp lệ sau 1 phút ({len(valid_files)} file). Đã lưu debug_test_data.html"

            post_data = cases_data
            post_data.update({
                'csrfmiddlewaretoken': self._get_csrf(r_page.text),
                'submit': 'Apply!',
                'problem-data-grader': 'standard',
                'problem-data-checker': 'standard',
                'problem-data-checker_type': 'default',
                'problem-data-io_method': 'standard',
                'problem-data-io_input_file': '',
                'problem-data-io_output_file': '',
            })
            
            r_save = self.session.post(url, data=post_data, headers={'Referer': url})
            if r_save.status_code in [200, 302]:
                return True, f"Đã cấu hình {total_cases} testcases thành công."
            return False, f"Lỗi lưu cấu hình (Status {r_save.status_code})."
        except Exception as e:
            return False, f"Lỗi Apply: {e}"
    
    def _extract_valid_files(self, html):
        """Trích xuất danh sách file từ HTML (mạnh tay)."""
        # 1. Tìm trong window.valid_files (chuẩn DMOJ)
        match = re.search(r'window\.valid_files\s*=\s*(\[.*?\])', html, re.DOTALL)
        if match:
            try:
                import ast; return ast.literal_eval(match.group(1))
            except: pass

        # 2. Tìm thủ công trong trang nếu bước 1 thất bại
        valid_files = []
        # Danh sách đuôi file mở rộng hơn
        suffixes = ('.in', '.out', '.ans', '.ok', '.inp', '.txt', '.a', '.sol', '.res', '.dat')
        
        soup = self._make_soup(html)
        # Quét mọi thẻ có văn bản
        for element in soup.find_all(['td', 'a', 'span', 'tr', 'li']):
            txt = element.get_text().strip()
            # Loại bỏ khoảng trắng và ký tự không in được
            txt = re.sub(r'[\s]+', ' ', txt).strip()
            
            # Tìm xem có chuỗi nào kết thúc bằng đuôi file không (dùng regex để chính xác hơn)
            for s in suffixes:
                # Regex tìm chuỗi kết thúc bằng .suffix
                # Đảm bảo không lấy chuỗi quá dài hoặc chứa ký tự đặc biệt
                pattern = rf'([a-zA-Z0-9_\-\.]{{1,64}}\{s})'
                m = re.search(pattern, txt, re.I)
                if m:
                    fname = m.group(1)
                    if fname not in valid_files:
                        valid_files.append(fname)
        
        return valid_files
