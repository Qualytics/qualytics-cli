from setuptools import setup, find_packages
import os

this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, "README.md")) as f:
    long_description = f.read()

project_urls = {
    "GitHub": "https://github.com/Qualytics/qualytics-cli",
    "Userguide": "https://qualytics.github.io/userguide/",
}
__version__ = "0.1.18"
setup(
    name="qualytics-cli",
    packages=find_packages(),
    version=__version__,
    license="MIT",
    long_description=long_description,
    long_description_content_type="text/markdown",
    description="Qualytics CLI",
    author="Qualytics",
    author_email="devops@qualytics.co",
    url="https://www.qualytics.co/",
    project_urls=project_urls,
    keywords=["Qualytics", "Data Quality"],
    include_package_data=True,
    install_requires=[
        "typer[all]",
        "requests",
        "pyjwt",
        "croniter",
    ],
    entry_points={"console_scripts": ["qualytics=qualytics.qualytics:app"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
