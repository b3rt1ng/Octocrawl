import importlib.util
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Any
import sys

from .example import BaseModule, CrawlContext


class ModuleManager:
    """Centralized manager for OctoCrawl modules"""
    
    def __init__(self, modules_dir: Path = None):
        if modules_dir is None:
            self.modules_dir = Path(__file__).parent
        else:
            self.modules_dir = Path(modules_dir)
        
        self.available_modules: Dict[str, BaseModule] = {}
        self.loaded_modules: List[BaseModule] = []
    
    def discover_modules(self) -> List[str]:
        discovered = []
        
        if not self.modules_dir.exists():
            return discovered
        
        for file in self.modules_dir.glob("*.py"):
            if file.name in ['__init__.py', 'example.py', 'module_manager.py']:
                continue
            discovered.append(file.stem)
        
        return discovered
    
    def load_module(self, module_name: str) -> Optional[BaseModule]:
        try:
            module_file = self.modules_dir / f"{module_name}.py"
            
            if not module_file.exists():
                print(f"❌ Module file '{module_file}' not found")
                return None
            
            # Nom complet dans le namespace octocrawl.modules pour que
            # les imports relatifs (from .example import ...) fonctionnent
            full_module_name = f"octocrawl.modules.{module_name}"

            spec = importlib.util.spec_from_file_location(
                full_module_name,
                module_file,
                submodule_search_locations=[]
            )
            
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)

                # Enregistrer dans sys.modules avant exec pour que les
                # imports relatifs trouvent le package parent
                module.__package__ = "octocrawl.modules"
                sys.modules[full_module_name] = module
                spec.loader.exec_module(module)
                
                for item_name in dir(module):
                    item = getattr(module, item_name)
                    if (isinstance(item, type) and 
                        issubclass(item, BaseModule) and 
                        item != BaseModule):
                        
                        instance = item()
                        instance.metadata = instance.get_metadata()
                        
                        success, missing = instance.validate_requirements()
                        if not success:
                            print(f"⚠️  Module '{module_name}' missing dependencies: {', '.join(missing)}")
                            return None
                        
                        self.available_modules[module_name] = instance
                        return instance
            
            print(f"❌ Could not load module '{module_name}'")
            return None
            
        except Exception as e:
            print(f"❌ Error loading module '{module_name}': {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def load_all_modules(self) -> int:
        discovered = self.discover_modules()
        loaded_count = 0
        
        for module_name in discovered:
            if self.load_module(module_name):
                loaded_count += 1
        
        return loaded_count
    
    def enable_module(self, module_name: str) -> bool:
        if module_name in self.available_modules:
            module = self.available_modules[module_name]
            module.enabled = True
            if module not in self.loaded_modules:
                self.loaded_modules.append(module)
            return True
        return False
    
    def disable_module(self, module_name: str) -> bool:
        if module_name in self.available_modules:
            module = self.available_modules[module_name]
            module.enabled = False
            if module in self.loaded_modules:
                self.loaded_modules.remove(module)
            return True
        return False
    
    def list_modules(self, category: str = None) -> List[Dict[str, Any]]:
        modules_info = []
        
        for name, module in self.available_modules.items():
            if category and module.metadata.category != category:
                continue
            
            modules_info.append({
                'name': name,
                'version': module.metadata.version,
                'description': module.metadata.description,
                'author': module.metadata.author,
                'category': module.metadata.category,
                'enabled': module.enabled,
                'requires': module.metadata.requires
            })
        
        return modules_info
    
    async def run_modules(self, context: CrawlContext) -> Dict[str, Any]:
        results = {}
        
        for module in self.loaded_modules:
            if not module.enabled:
                continue
            
            try:
                print(f"\n🔧 Running module: {module.metadata.name}")
                
                if not module.setup(context):
                    print(f"❌ Setup failed for module '{module.metadata.name}'")
                    continue
                
                result = await module.run(context)
                results[module.metadata.name] = {
                    'success': True,
                    'data': result
                }
                
                print(f"✅ Module '{module.metadata.name}' completed successfully")
                
            except Exception as e:
                print(f"❌ Error in module '{module.metadata.name}': {e}")
                import traceback
                traceback.print_exc()
                results[module.metadata.name] = {
                    'success': False,
                    'error': str(e)
                }
            
            finally:
                try:
                    module.cleanup()
                except Exception as e:
                    print(f"⚠️  Cleanup error in module '{module.metadata.name}': {e}")
        
        return results
    
    async def run_single_module(
        self, 
        module_name: str, 
        context: CrawlContext
    ) -> Optional[Dict[str, Any]]:
        if module_name not in self.available_modules:
            print(f"❌ Module '{module_name}' not found")
            return None
        
        module = self.available_modules[module_name]
        
        try:
            print(f"\n🔧 Running module: {module.metadata.name}")
            
            if not module.setup(context):
                print(f"❌ Setup failed for module '{module_name}'")
                return None
            
            result = await module.run(context)
            print(f"✅ Module '{module_name}' completed successfully")
            module.cleanup()
            
            return {'success': True, 'data': result}
            
        except Exception as e:
            print(f"❌ Error in module '{module_name}': {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
        
        finally:
            try:
                module.cleanup()
            except:
                pass