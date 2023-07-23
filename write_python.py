import describe
from typing import TextIO


class File:
    def __init__(self, discovery_dict: dict) -> None:
        self.classes: dict[str, 'Class'] = {}
        self.imports: list[str] = []

        schemas: dict = discovery_dict['schemas']
        for schema_name, schema_dict in schemas.items():
            self.add_class(schema_name, schema_dict)
        del discovery_dict['schemas']

        api_id: str = discovery_dict['id']
        self.add_class(''.join(i.capitalize() for i in api_id.split(':')),
                       discovery_dict)

        self.file_name = f"{'_'.join(i.lower() for i in api_id.split(':'))}.py"

    def add_class(self, class_name: str, class_dict: dict):
        self.classes[class_name] = Class(class_name, class_dict)


class Class:
    def __init__(self, class_name: str, class_dict: dict) -> None:
        self.class_name = class_name
        self.methods: list[Method] = []
        self.class_attributes: list[Attribute] = []
        self.attributes: list[Attribute] = []
        self.class_dependencies: list[Class] = []
        self.import_dependencies: list[str] = []
        self.description: str = None

        self.load_dict(class_dict)

    def load_dict(self, class_dict: dict):
        for key, value in class_dict.items():
            if type(value) is not dict:
                self.add_attribute(key, value)
            if key == 'properties':
                self.add_properties(value)
            if key == 'description':
                self.description = value
            if key == 'resources':
                self.add_resources(value)


    def add_attribute(self, name: str, value, comment: str | None = None,
                      type_: str | None = None):
        self.attributes.append(Attribute(name, value, comment, type_))

    def add_class_attribute(self, name: str, value, comment: str | None = None,
                            type_: str | None = None):
        self.class_attributes.append(Attribute(name, value, comment, type_))

    def add_properties(self, properties: dict):
        for name, info in properties.items():
            if 'type' in info:
                type_ = info['type']
            elif '$ref' in info:
                type_ = info['$ref']
                self.class_dependencies.append(type_)
            else:
                type_ = None
            self.add_class_attribute(name, None, info['description'], type_)

    def add_resources(self, methods: dict):
        for resource_name, resource in methods.items():
            ...



class Attribute:
    translate_dict = {'string': 'str',
                      'boolean': 'bool',
                      'array': 'list',
                      'object': 'dict'}

    def __init__(self, name: str, value, annotations: str | None = None, type_: str | None = None) -> None:
        self.name = name
        self.value = value
        if type_ is None:
            self.type = type(self.value).__name__
        else:
            self.type = Attribute.translate_type(type_)
        if isinstance(self.value, str):
            self.value = f'"{self.value}"'
        self.annotations = "" if annotations is None else annotations

    @classmethod
    def translate_type(cls, type_in_json: str) -> str:
        try:
            return cls.translate_dict[type_in_json]
        except KeyError:
            return type_in_json


class Method:
    def __init__(self, name: str) -> None:
        self.name = name
        self.arguments = list[MethodArgument] = []
        self.return_value = str


class MethodArgument:
    ...


class Indentation:
    def __init__(self) -> None:
        self.indent = 0
        self.spaces = 4

    def __add__(self, val):
        if not isinstance(val, int):
            raise TypeError
        if self.indent + val < 0:
            raise ValueError
        self.indent += val
        return self

    def __sub__(self, val):
        if not isinstance(val, int):
            raise TypeError
        if self.indent - val < 0:
            raise ValueError
        self.indent -= val
        return self

    def __str__(self) -> str:
        return " " * self.indent * self.spaces


class PythonWriter:
    indentation = Indentation()

    def __init__(self, output_file: TextIO) -> None:
        self.output_file = output_file

    def write_line(self, content: str | None = None):
        content = "" if content is None else content
        content = f"{self.indentation}{content}".rstrip()
        self.output_file.write(f"{content}\n")


class FileWriter(PythonWriter):
    def __init__(self, file: File) -> None:
        PythonWriter.__init__(self, open(f"dump_folder/{file.file_name}",
                                         mode='w'))
        self.file = file
        self.written_classes: set[str] = set()

    def write_class(self, class_: Class):
        if class_.class_name in self.written_classes:
            return
        self.written_classes.add(class_.class_name)
        
        for dependency_class in class_.class_dependencies:
            self.write_class(self.file.classes[dependency_class])

        ClassWriter(class_, self.output_file).write()

    def write(self):
        for class_name, class_ in self.file.classes.items():
            self.write_class(class_)


class ClassWriter(PythonWriter):
    def __init__(self, class_: Class, output_file: TextIO) -> None:
        PythonWriter.__init__(self, output_file)
        self.class_ = class_

    def write(self):
        self.write_line(f"class {self.class_.class_name}:")
        self.indentation += 1
        self.write_class_description()
        self.write_class_attributes()
        self.indentation -= 1
        self.write_line()
        self.write_line()

    def write_class_description(self):
        if self.class_.description is None:
            return
        
        self.write_line("'''")
        self.write_line(self.class_.description)
        self.write_line("'''")

    def write_class_attributes(self):
        for attribute in self.class_.attributes:
            AttributeWriter(attribute, self.output_file).write()
            self.write_line()
        for attribute in self.class_.class_attributes:
            AttributeWriter(attribute, self.output_file).write()
            self.write_line()


class AttributeWriter(PythonWriter):
    def __init__(self, attribute: Attribute, output_file: TextIO) -> None:
        PythonWriter.__init__(self, output_file)
        self.attribute = attribute

    def write(self):
        if self.attribute.annotations:
            for sentence in self.attribute.annotations.split('\n'):
                self.write_line(f"# {sentence}")
        assign_value = "" if self.attribute.value is None else f" = {self.attribute.value}"
        self.write_line(f"{self.attribute.name}: {self.attribute.type}"
                        f"{assign_value}")


def get_discovery(api_id: str):
    return describe.generate_discovery_api(api_id)


def main():
    a = get_discovery('blogger:v3')
    blogger_file = File(a)
    FileWriter(blogger_file).write()
    pass
    b = get_discovery('drive:v3')
    driver_file = File(b)
    FileWriter(driver_file).write()


if __name__ == '__main__':
    main()
