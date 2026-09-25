"""
Security Headers Module for OctoCrawl
Analyzes security headers and provides recommendations
"""

from typing import Dict, Any, List
from collections import Counter

from .example import BaseModule, ModuleMetadata, CrawlContext


class SecurityHeadersModule(BaseModule):
    """
    Analyzes security headers across the site
    """
    
    # Important security headers to check
    SECURITY_HEADERS = {
        'strict-transport-security': {
            'name': 'HSTS (Strict-Transport-Security)',
            'description': 'Forces HTTPS connections',
            'severity': 'HIGH'
        },
        'content-security-policy': {
            'name': 'Content-Security-Policy',
            'description': 'Prevents XSS and injection attacks',
            'severity': 'HIGH'
        },
        'x-frame-options': {
            'name': 'X-Frame-Options',
            'description': 'Prevents clickjacking',
            'severity': 'MEDIUM'
        },
        'x-content-type-options': {
            'name': 'X-Content-Type-Options',
            'description': 'Prevents MIME sniffing',
            'severity': 'MEDIUM'
        },
        'referrer-policy': {
            'name': 'Referrer-Policy',
            'description': 'Controls referrer information',
            'severity': 'LOW'
        },
        'permissions-policy': {
            'name': 'Permissions-Policy',
            'description': 'Controls browser features',
            'severity': 'LOW'
        },
        'x-xss-protection': {
            'name': 'X-XSS-Protection',
            'description': 'Legacy XSS protection',
            'severity': 'LOW'
        }
    }
    
    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="headers",
            version="1.0.0",
            description="Analyzes security headers and provides recommendations",
            author="@b3rt1ng",
            requires=[],
            category="security"
        )
    
    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        """Analyzes security headers"""
        
        self.log("Analyzing security headers...", "INFO")

        pages = context.response_headers
        if not pages:
            self.log("No HTML page headers collected during the crawl", "WARNING")
            return {'security_score': None, 'pages_analyzed': 0}

        found_headers = {}
        missing_headers = []
        
        for header_key, header_info in self.SECURITY_HEADERS.items():
            # httpx lowercases header names, so a plain lookup is enough
            values = [headers[header_key] for headers in pages.values() if header_key in headers]

            if values:
                found_headers[header_key] = {
                    'name': header_info['name'],
                    'value': Counter(values).most_common(1)[0][0],
                    'coverage': len(values) / len(pages),
                    'pages_with': len(values),
                    'severity': header_info['severity'],
                    'description': header_info['description']
                }
            else:
                missing_headers.append({
                    'key': header_key,
                    'name': header_info['name'],
                    'severity': header_info['severity'],
                    'description': header_info['description']
                })
        
        total_headers = len(self.SECURITY_HEADERS)
        found_count = len(found_headers)
        
        # Weighted scoring based on severity, scaled by how many pages actually send
        # the header: HSTS on the homepage only is not the same as HSTS everywhere
        def weight(severity):
            return 3 if severity == 'HIGH' else 2 if severity == 'MEDIUM' else 1

        max_score = sum(weight(h['severity']) for h in self.SECURITY_HEADERS.values())
        current_score = sum(weight(h['severity']) * h['coverage'] for h in found_headers.values())
        
        security_score = (current_score / max_score * 100) if max_score > 0 else 0
        
        # Generate report
        report = self._generate_report(
            context,
            found_headers,
            missing_headers,
            security_score,
            len(pages)
        )
        
        # Save report
        md_file = self.save_output(
            "security_headers.md",
            report
        )
        
        severity = "🟢 GOOD" if security_score > 70 else "🟡 WARNING" if security_score > 40 else "🔴 CRITICAL"
        
        self.log(f"Security score: {security_score:.1f}% ({severity}) over {len(pages)} page(s)", "INFO")
        self.log(f"Found {found_count}/{total_headers} security headers", "INFO")
        for header in found_headers.values():
            if header['coverage'] < 1:
                self.log(f"  {header['name']} only sent on {header['pages_with']}/{len(pages)} pages", "WARNING")
        self.log(f"Report saved to {md_file}", "INFO")
        
        return {
            'security_score': round(security_score, 2),
            'severity': severity,
            'pages_analyzed': len(pages),
            'found_headers': len(found_headers),
            'missing_headers': len(missing_headers),
            'total_headers': total_headers,
            'output_file': str(md_file)
        }
    
    def _generate_report(
        self,
        context: CrawlContext,
        found_headers: Dict,
        missing_headers: List[Dict],
        security_score: float,
        pages_analyzed: int
    ) -> str:
        """Generates a markdown report"""
        
        if security_score > 70:
            score_emoji = "🟢"
            score_status = "GOOD"
        elif security_score > 40:
            score_emoji = "🟡"
            score_status = "NEEDS IMPROVEMENT"
        else:
            score_emoji = "🔴"
            score_status = "CRITICAL"
        
        report = f"""# Security Headers Analysis

**Target:** {context.start_url}  
**Security Score:** {score_emoji} {security_score:.1f}% ({score_status})  
**Pages analyzed:** {pages_analyzed}

---

## Summary

- ✅ **Found**: {len(found_headers)} security headers
- ❌ **Missing**: {len(missing_headers)} security headers

---

## ✅ Present Headers

"""
        
        if found_headers:
            for header_key, header_data in sorted(found_headers.items()):
                severity_emoji = "🔴" if header_data['severity'] == 'HIGH' else "🟡" if header_data['severity'] == 'MEDIUM' else "🔵"
                report += f"\n### {severity_emoji} {header_data['name']}\n\n"
                report += f"**Severity**: {header_data['severity']}  \n"
                report += f"**Description**: {header_data['description']}  \n"
                report += f"**Coverage**: {header_data['pages_with']}/{pages_analyzed} pages  \n"
                report += f"**Value**: `{header_data['value']}`\n"
        else:
            report += "*No security headers detected*\n"
        
        report += "\n---\n\n## ❌ Missing Headers\n\n"
        
        if missing_headers:
            # Sort by severity
            severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
            sorted_missing = sorted(
                missing_headers,
                key=lambda x: severity_order.get(x['severity'], 3)
            )
            
            for header in sorted_missing:
                severity_emoji = "🔴" if header['severity'] == 'HIGH' else "🟡" if header['severity'] == 'MEDIUM' else "🔵"
                report += f"\n### {severity_emoji} {header['name']}\n\n"
                report += f"**Severity**: {header['severity']}  \n"
                report += f"**Description**: {header['description']}  \n"
                report += f"**Recommendation**: Implement this header\n"
        else:
            report += "✅ *All recommended headers are present!*\n"
        
        report += """

---

## 💡 Recommendations

### High Priority
1. **Implement HSTS**: Add `Strict-Transport-Security: max-age=31536000; includeSubDomains`
2. **Set CSP**: Create a Content-Security-Policy to prevent XSS attacks
3. **Enable X-Frame-Options**: Set to `DENY` or `SAMEORIGIN` to prevent clickjacking

### Medium Priority
4. **Add X-Content-Type-Options**: Set to `nosniff`
5. **Configure Referrer-Policy**: Use `strict-origin-when-cross-origin`

### Resources
- [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/)
- [Mozilla Observatory](https://observatory.mozilla.org/)
- [Security Headers](https://securityheaders.com/)

"""
        
        return report